import asyncio
import logging
import time
import hashlib
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple
from curl_cffi import requests as cffi_requests
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from .models import TorrentItem
from .parser import ExtToParser, extract_infohash
from app.cache.db import CacheDatabase

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Markers that ONLY appear on a Cloudflare interstitial / block page.
CF_STRONG_MARKERS = (
    "just a moment",
    "attention required!",
    "verify you are human",
    "enable javascript and cookies to continue",
    "performing security verification",
    "window._cf_chl_opt",
    "challenge-error-text",
    "cf-chl-widget",
)

# Markers that ALSO appear on perfectly healthy pages (every Cloudflare-fronted
# page loads `/cdn-cgi/challenge-platform/scripts/jsd/main.js`, and Turnstile
# widgets are embedded in ordinary forms), so they only count as a challenge when
# the response contains no expected page content at all.
CF_WEAK_MARKERS = (
    "cdn-cgi/challenge-platform",
    "cf-turnstile",
    "challenges.cloudflare.com",
)

CONTENT_MARKERS = (
    "<table",
    "<tbody",
    "/torrent/",
    "torrent-table",
)

SESSION_STATE_KEY = "cf_session"


class ExtToScraper:
    """Resilient scraper for ext.to / extto.com using curl_cffi Chrome TLS impersonation and Playwright fallback."""

    def __init__(
        self,
        base_url: str = "https://ext.to",
        headless: bool = True,
        timeout: int = 30,
        flaresolverr_url: Optional[str] = None,
        cache_db: Optional[CacheDatabase] = None,
        proxy_url: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        user_agent: Optional[str] = None,
        impersonate: str = "chrome120",
        challenge_wait_seconds: int = 45,
        browser_channel: Optional[str] = None,
        solve_challenge: bool = True,
        max_solve_clicks: int = 2,
        solve_click_gap_seconds: int = 20,
    ):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout = timeout
        self.flaresolverr_url = flaresolverr_url
        self.cache_db = cache_db
        self.proxy_url = proxy_url or None
        self.user_agent = user_agent or None
        self.impersonate = impersonate
        self.challenge_wait_seconds = challenge_wait_seconds
        self.browser_channel = browser_channel
        self.solve_challenge = solve_challenge
        self.max_solve_clicks = max_solve_clicks
        self.solve_click_gap_seconds = solve_click_gap_seconds
        self.parser = ExtToParser(base_url=self.base_url)
        self.mirror_domains = [
            self.base_url,
            "https://ext.to",
            "https://extto.com",
            "https://ext2.to",
        ]
        self._working_domain: Optional[str] = None
        self._browser_sem = asyncio.Semaphore(1)
        self._session_lock = asyncio.Lock()

        # Cloudflare clearance cookies shared by the curl_cffi fast path and the
        # Playwright fallback (cf_clearance is bound to egress IP + User-Agent).
        self._cookies: Dict[str, str] = {}
        if cf_clearance:
            self._cookies["cf_clearance"] = cf_clearance
        self._session_loaded = bool(cf_clearance)
        self._browser_user_agent: Optional[str] = None

    # ---------------------------------------------------------------- session

    @property
    def effective_user_agent(self) -> str:
        """UA used for every request; harvested from the browser when not configured."""
        return self.user_agent or self._browser_user_agent or DEFAULT_USER_AGENT

    @property
    def filtered_cookie_header(self) -> Optional[str]:
        """Cookie header value for cloud-protection cookies, or None."""
        if not self._cookies:
            return None
        return "; ".join(f"{name}={value}" for name, value in self._cookies.items())

    async def _load_session_state(self) -> None:
        """Load persisted clearance cookies (survive restarts / container recreates)."""
        if self._session_loaded:
            return
        async with self._session_lock:
            if self._session_loaded:
                return
            if self.cache_db:
                state = await self.cache_db.get_session_state(SESSION_STATE_KEY)
                if state:
                    cookies = state.get("cookies") or {}
                    if isinstance(cookies, dict):
                        self._cookies.update(
                            {k: v for k, v in cookies.items() if isinstance(v, str) and v}
                        )
                    ua = state.get("browser_user_agent")
                    if isinstance(ua, str) and ua:
                        self._browser_user_agent = ua
                    if self._cookies:
                        logger.info(
                            f"Loaded persisted session cookies: {', '.join(sorted(self._cookies))}"
                        )
            self._session_loaded = True

    async def _store_session_state(self, cookies: Dict[str, str]) -> None:
        """Persist freshly harvested clearance cookies so curl_cffi can reuse them."""
        fresh = {
            name: value
            for name, value in cookies.items()
            if value and (name.startswith("cf") or name.startswith("__cf") or name == "PHPSESSID")
        }
        if not fresh:
            return
        self._cookies.update(fresh)
        logger.info(f"Harvested Cloudflare cookies from browser: {', '.join(sorted(fresh))}")
        if self.cache_db:
            await self.cache_db.set_session_state(
                SESSION_STATE_KEY,
                {"cookies": self._cookies, "browser_user_agent": self._browser_user_agent},
            )

    def _domains(self) -> List[str]:
        """Mirror domains, trying the last known working one first."""
        seen = set()
        ordered: List[str] = []
        for domain in ([self._working_domain] if self._working_domain else []) + self.mirror_domains:
            if domain and domain not in seen:
                seen.add(domain)
                ordered.append(domain)
        return ordered

    # ---------------------------------------------------------------- search

    async def search(self, query: str, page: int = 1, category: Optional[str] = None, max_magnets: int = 25) -> List[TorrentItem]:
        """Search ext.to for a query string and return parsed TorrentItem list with magnet links."""
        encoded_query = urllib.parse.quote_plus(query)
        await self._load_session_state()

        # Build browse URL pattern
        path = f"/browse/?q={encoded_query}&page={page}"
        if category:
            path += f"&cat={category}"

        # 1. Try fast curl_cffi Chrome TLS impersonation across mirror domains
        html, current_base = await self._fetch_with_curl_cffi(path)
        challenged = html is not None and self._is_cloudflare_challenge(html)

        # 2. If configured, delegate Cloudflare clearance to a FlareSolverr instance
        if (not html or challenged) and self.flaresolverr_url:
            logger.info("Attempting FlareSolverr fetch...")
            try:
                fs_html, fs_base = await self._fetch_with_flaresolverr(path)
                if fs_html:
                    html, current_base, challenged = fs_html, fs_base, False
            except Exception as e:
                logger.error(f"FlareSolverr fetch failed: {e}")

        # 3. If still blocked by Cloudflare, fall back to local Playwright stealth browser
        if not html or challenged:
            logger.info("Cloudflare Turnstile challenge detected. Launching Playwright Stealth fallback...")
            try:
                html, current_base = await self._fetch_with_playwright(path)
            except Exception as e:
                logger.error(f"Playwright fallback encountered an unexpected error: {e}")
                html = None

        # 4. The browser can end up holding a valid cf_clearance even when its own
        #    page stayed on the interstitial - the cookie alone is often enough for
        #    the HTTP path, which is far cheaper than another browser round trip.
        if (not html or self._is_cloudflare_challenge(html)) and self._cookies.get("cf_clearance"):
            logger.info("Retrying curl_cffi with the freshly harvested clearance cookie...")
            retry_html, retry_base = await self._fetch_with_curl_cffi(path)
            if retry_html and not self._is_cloudflare_challenge(retry_html):
                html, current_base = retry_html, retry_base

        # 5. Give up: every backend is still behind the Cloudflare challenge.
        if not html or self._is_cloudflare_challenge(html):
            logger.error("Failed to fetch ext.to search results HTML from all backends.")
            return []

        # Update parser base domain
        self.parser.base_url = current_base

        # Parse table rows into dictionaries
        raw_items = self.parser.parse_search_results(html)
        logger.info(f"Scraped {len(raw_items)} raw torrent items from {current_base}")

        # Resolve magnet links with concurrency limit for top results up to max_magnets
        sem = asyncio.Semaphore(5)

        async def _resolve_with_sem(url: str, tid: Optional[int]):
            async with sem:
                return await self.resolve_magnet_for_item(url, tid)

        magnet_tasks = []
        for idx, raw in enumerate(raw_items):
            if idx < max_magnets and raw.get("details_url"):
                magnet_tasks.append(_resolve_with_sem(raw["details_url"], raw.get("torrent_id")))
            else:
                magnet_tasks.append(asyncio.sleep(0, result=(None, None)))

        resolved_magnets = await asyncio.gather(*magnet_tasks, return_exceptions=True)

        torrent_items: List[TorrentItem] = []
        for raw, res in zip(raw_items, resolved_magnets):
            magnet_link = None
            infohash = None

            if isinstance(res, tuple) and res:
                magnet_link, infohash = res

            item = TorrentItem(
                title=raw["title"],
                details_url=raw["details_url"],
                magnet_link=magnet_link,
                infohash=infohash,
                size_bytes=raw["size_bytes"],
                size_human=raw["size_human"],
                seeders=raw["seeders"],
                leechers=raw["leechers"],
                category=raw["category"],
                pub_date=raw["pub_date"],
            )
            torrent_items.append(item)

        return torrent_items

    async def resolve_magnet_for_item(self, details_url: str, torrent_id: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
        """Fetch detail page, extract tokens, compute HMAC, and retrieve magnet link and infohash."""
        # Extract torrent_id if not provided
        if not torrent_id:
            id_match = re.search(r"-(\d+)/?$", details_url)
            if id_match:
                torrent_id = int(id_match.group(1))

        # Check magnet cache if available
        if self.cache_db and torrent_id:
            cached = await self.cache_db.get_magnet_cache(torrent_id)
            if cached and cached[0]:
                logger.debug(f"Magnet cache HIT for torrent_id {torrent_id}")
                return cached[0], cached[1]

        loop = asyncio.get_running_loop()
        headers = self._request_headers(extra={"X-Requested-With": "XMLHttpRequest"})

        try:
            # 1. Fetch detail page HTML
            def _fetch_detail():
                with cffi_requests.Session(impersonate=self.impersonate, proxies=self._proxies()) as s:
                    r = s.get(details_url, headers=headers, timeout=self.timeout)
                    return r.text

            html = await loop.run_in_executor(None, _fetch_detail)
            if not html or self._is_cloudflare_challenge(html):
                logger.debug(f"Detail page for {details_url} was challenged or empty")
                return None, None

            # Extract CSRF and Page Tokens
            csrf_token, page_token = self.parser.parse_tokens(html)

            if not torrent_id or not csrf_token or not page_token:
                return None, None

            # 2. Compute SHA256 HMAC
            timestamp = int(time.time())
            raw_token_data = f"{torrent_id}|{timestamp}|{page_token}"
            hmac_hash = hashlib.sha256(raw_token_data.encode("utf-8")).hexdigest()

            parsed_url = urllib.parse.urlparse(details_url)
            domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

            post_data = {
                "torrent_id": torrent_id,
                "download_type": "magnet",
                "timestamp": timestamp,
                "hmac": hmac_hash,
                "sessid": csrf_token,
            }

            api_url = f"{domain}/ajax/getTorrentMagnet.php"

            def _post_magnet():
                with cffi_requests.Session(impersonate=self.impersonate, proxies=self._proxies()) as s:
                    resp = s.post(api_url, data=post_data, headers={**headers, "Referer": details_url}, timeout=10)
                    return resp

            api_resp = await loop.run_in_executor(None, _post_magnet)
            if api_resp.status_code == 200:
                data = api_resp.json()
                if data.get("success") and data.get("url"):
                    magnet = data.get("url")
                    infohash = extract_infohash(magnet)

                    if self.cache_db and torrent_id:
                        await self.cache_db.set_magnet_cache(torrent_id, magnet, infohash)

                    return magnet, infohash

        except Exception as e:
            logger.debug(f"Failed resolving magnet for {details_url}: {e}")

        return None, None

    # ---------------------------------------------------------------- fetch

    def _proxies(self) -> Optional[Dict[str, str]]:
        if not self.proxy_url:
            return None
        return {"http": self.proxy_url, "https": self.proxy_url}

    def _request_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.effective_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookie_header = self.filtered_cookie_header
        if cookie_header:
            headers["Cookie"] = cookie_header
        if extra:
            headers.update(extra)
        return headers

    async def _fetch_with_curl_cffi(self, path: str) -> Tuple[Optional[str], str]:
        """Attempt fast HTTP fetch using curl_cffi Chrome TLS impersonation across mirror domains."""
        loop = asyncio.get_running_loop()
        headers = self._request_headers()

        for domain in self._domains():
            target_url = f"{domain}{path}"
            try:
                logger.info(f"Attempting curl_cffi TLS impersonation fetch to {target_url}...")

                def _do_req():
                    return cffi_requests.get(
                        target_url,
                        headers=headers,
                        impersonate=self.impersonate,
                        timeout=self.timeout,
                        proxies=self._proxies(),
                    )

                resp = await loop.run_in_executor(None, _do_req)
                mitigated = (resp.headers.get("cf-mitigated") or "").lower() == "challenge"
                if resp.status_code == 200 and not mitigated and not self._is_cloudflare_challenge(resp.text):
                    logger.info(f"Successfully fetched search results from {domain} via curl_cffi!")
                    return resp.text, domain
                if mitigated or self._is_cloudflare_challenge(resp.text):
                    logger.warning(
                        f"Domain {domain} is behind a Cloudflare challenge "
                        f"(HTTP {resp.status_code}, cf-mitigated={mitigated})"
                    )
                else:
                    logger.warning(f"Domain {domain} returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"curl_cffi fetch to {domain} failed: {e}")

        return None, self.base_url

    async def _fetch_with_flaresolverr(self, path: str) -> Tuple[Optional[str], str]:
        """Fetch via an external FlareSolverr instance (Cloudflare clearance proxy)."""
        if not self.flaresolverr_url:
            return None, self.base_url

        target_url = f"{self.base_url}{path}"
        loop = asyncio.get_running_loop()

        payload = {"cmd": "request.get", "url": target_url, "maxTimeout": 60000}
        if self.proxy_url:
            payload["proxy"] = {"url": self.proxy_url}

        def _do_req():
            return cffi_requests.post(
                self.flaresolverr_url,
                json=payload,
                timeout=self.timeout + 30,
            )

        resp = await loop.run_in_executor(None, _do_req)
        if resp.status_code != 200:
            logger.warning(f"FlareSolverr returned HTTP {resp.status_code}")
            return None, self.base_url

        data = resp.json()
        if data.get("status") != "ok" or not data.get("solution"):
            logger.warning(f"FlareSolverr did not solve challenge: {data.get('message')}")
            return None, self.base_url

        solution = data["solution"]
        html = solution.get("response")
        final_url = solution.get("url") or target_url
        parsed = urllib.parse.urlparse(final_url)
        domain = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else self.base_url

        # FlareSolverr returns the clearance in solution.cookies - keep it for curl_cffi.
        cookies: Dict[str, str] = {
            str(c.get("name")): str(c.get("value"))
            for c in solution.get("cookies", [])
            if isinstance(c, dict) and c.get("name") and c.get("value")
        }
        if cookies:
            await self._store_session_state(cookies)

        if not html or self._is_cloudflare_challenge(html):
            return None, domain

        logger.info(f"Successfully fetched search results from {domain} via FlareSolverr!")
        return html, domain

    def _launch_options(self) -> Dict:
        """Chromium launch options (kept Chromium rather than the headless shell so
        stealth still works, with fonts required to avoid a Skia FATAL crash)."""
        options: Dict = {
            "headless": self.headless,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-crash-reporter",
                "--no-first-run",
            ],
        }
        if self.proxy_url:
            options["proxy"] = {"server": self.proxy_url}
        if self.browser_channel:
            options["channel"] = self.browser_channel
        return options

    async def _new_context(self, browser):
        """Create a context that reuses harvested clearance cookies and the shared UA."""
        return await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=self.effective_user_agent,
            locale="en-US",
            timezone_id="Europe/London",
        )

    async def _await_challenge_resolution(self, page) -> Optional[str]:
        """Poll a navigating page until Cloudflare clears it (or we run out of time).

        A managed challenge needs several seconds of JS execution and, for ext.to,
        an actual click on the Turnstile "Verify you are human" checkbox - it never
        clears on its own. Reading `page.content()` immediately after
        `domcontentloaded` (the previous behaviour) always returned the interstitial.
        """
        deadline = time.monotonic() + max(1, self.challenge_wait_seconds)
        click_attempts = 0
        last_click = -1e9
        html: Optional[str] = None
        while True:
            try:
                html = await page.content()
            except Exception as e:
                logger.warning(f"Lost the page while waiting for the challenge: {e}")
                return None
            if not self._is_cloudflare_challenge(html):
                return html

            now = time.monotonic()
            if (
                self.solve_challenge
                and click_attempts < self.max_solve_clicks
                and now - last_click >= self.solve_click_gap_seconds
            ):
                # Click at most a couple of times with a generous gap: repeatedly
                # hammering the widget makes Cloudflare escalate to a challenge that
                # will not clear at all (observed after ~40 rapid attempts).
                clicked = await self._click_turnstile_widget(page, click_attempts)
                if clicked:
                    click_attempts += 1
                    last_click = time.monotonic()

            if time.monotonic() >= deadline:
                logger.warning(
                    f"Cloudflare challenge still present after {self.challenge_wait_seconds}s "
                    f"({click_attempts} widget click(s) attempted)"
                )
                return html
            await asyncio.sleep(2.0)

    async def _click_turnstile_widget(self, page, attempt: int = 0) -> bool:
        """Click the Cloudflare Turnstile widget (cross-origin iframe) by coordinates.

        Playwright cannot reach inside the challenge iframe's shadow DOM, but the
        widget accepts a real mouse click on the checkbox, which is what clears the
        challenge for ext.to.
        """
        try:
            frames = [
                f for f in page.frames
                if "challenges.cloudflare.com" in (f.url or "")
            ]
            if not frames:
                return False
            element = await frames[0].frame_element()
            box = await element.bounding_box()
            if not box or not box.get("width"):
                return False

            if attempt == 0:
                x = box["x"] + box["width"] / 2          # widget centre
            else:
                x = box["x"] + box["width"] * 0.12       # checkbox column
            y = box["y"] + box["height"] / 2

            await page.mouse.move(max(0, x - 20), max(0, y - 20))
            await asyncio.sleep(0.4)
            await page.mouse.click(x, y)
            logger.info(f"Clicked Cloudflare Turnstile widget at ({x:.0f}, {y:.0f})")
            return True
        except Exception as e:
            logger.debug(f"Could not click Turnstile widget: {e}")
            return False

    async def _fetch_with_playwright(self, path: str) -> Tuple[Optional[str], str]:
        """Fallback Playwright stealth scraper for Cloudflare Turnstile pages.

        Iterates all mirror domains within a single browser session, waits for the
        challenge to clear, and harvests the resulting clearance cookies for the
        curl_cffi fast path.
        """
        async with self._browser_sem:
            try:
                async with async_playwright() as p:
                    try:
                        browser = await p.chromium.launch(**self._launch_options())
                    except Exception as e:
                        logger.warning(f"Chromium launch with configured options failed ({e}); retrying defaults")
                        fallback = self._launch_options()
                        fallback.pop("channel", None)
                        browser = await p.chromium.launch(**fallback)

                    try:
                        for domain in self._domains():
                            target_url = f"{domain}{path}"
                            context = None
                            try:
                                context = await self._new_context(browser)
                                if self._cookies:
                                    await context.add_cookies([
                                        {
                                            "name": name,
                                            "value": value,
                                            "domain": urllib.parse.urlparse(domain).hostname or "ext.to",
                                            "path": "/",
                                        }
                                        for name, value in self._cookies.items()
                                    ])
                                page = await context.new_page()
                                await Stealth().apply_stealth_async(page)

                                await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)

                                if not self._browser_user_agent:
                                    try:
                                        self._browser_user_agent = await page.evaluate("navigator.userAgent")
                                    except Exception:
                                        pass

                                content = await self._await_challenge_resolution(page)

                                try:
                                    cookies: Dict[str, str] = {
                                        str(c["name"]): str(c["value"])
                                        for c in await context.cookies()
                                        if c.get("name") and c.get("value")
                                    }
                                    await self._store_session_state(cookies)
                                except Exception as e:
                                    logger.debug(f"Could not read browser cookies: {e}")

                                # Cloudflare usually refreshes the page itself once the
                                # widget is solved; if it did not, re-request now that we
                                # hold cf_clearance.
                                if (
                                    content
                                    and self._is_cloudflare_challenge(content)
                                    and self._cookies.get("cf_clearance")
                                ):
                                    logger.info("Clearance obtained but page not refreshed - re-requesting")
                                    try:
                                        await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                                        content = await self._await_challenge_resolution(page)
                                    except Exception as e:
                                        logger.debug(f"Re-request after clearance failed: {e}")

                                if content and not self._is_cloudflare_challenge(content):
                                    self._working_domain = domain
                                    logger.info(f"Successfully fetched search results from {domain} via Playwright!")
                                    return content, domain
                                logger.warning(f"Playwright still challenged on {domain}")
                            except Exception as e:
                                logger.warning(f"Playwright navigation failed for {target_url}: {e}")
                            finally:
                                if context is not None:
                                    try:
                                        await context.close()
                                    except Exception:
                                        pass

                        return None, self.base_url
                    finally:
                        try:
                            await browser.close()
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Playwright launch failed: {e}")
                return None, self.base_url

    def _is_cloudflare_challenge(self, html: Optional[str]) -> bool:
        """Detect a Cloudflare interstitial/block page (not merely a Turnstile widget)."""
        if not html:
            return False
        lowered = html.lower()
        if any(marker in lowered for marker in CF_STRONG_MARKERS):
            return True
        if any(marker in lowered for marker in CF_WEAK_MARKERS):
            # Turnstile scripts also ship on healthy pages; only call it a
            # challenge when there is no page content whatsoever.
            return not any(marker in lowered for marker in CONTENT_MARKERS)
        return False
