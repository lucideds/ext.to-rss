import asyncio
import logging
import time
import hashlib
import re
import urllib.parse
from typing import List, Dict, Optional, Tuple
from curl_cffi import requests as cffi_requests
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from .models import TorrentItem
from .parser import ExtToParser, extract_infohash
from app.cache.db import CacheDatabase

logger = logging.getLogger(__name__)


class ExtToScraper:
    """Resilient scraper for ext.to / extto.com using curl_cffi Chrome TLS impersonation and Playwright fallback."""

    def __init__(
        self,
        base_url: str = "https://extto.com",
        headless: bool = True,
        timeout: int = 30,
        flaresolverr_url: Optional[str] = None,
        cache_db: Optional[CacheDatabase] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout = timeout
        self.flaresolverr_url = flaresolverr_url
        self.cache_db = cache_db
        self.parser = ExtToParser(base_url=self.base_url)
        self.mirror_domains = [
            self.base_url,
            "https://extto.com",
            "https://ext.to",
            "https://ext2.to",
        ]
        self._browser_sem = asyncio.Semaphore(1)

    async def search(self, query: str, page: int = 1, category: Optional[str] = None, max_magnets: int = 25) -> List[TorrentItem]:
        """Search ext.to for a query string and return parsed TorrentItem list with magnet links."""
        encoded_query = urllib.parse.quote_plus(query)
        
        # Build browse URL pattern
        path = f"/browse/?q={encoded_query}&page={page}"
        if category:
            path += f"&cat={category}"

        # 1. Try fast curl_cffi Chrome TLS impersonation across mirror domains
        html, current_base = await self._fetch_with_curl_cffi(path)

        # 2. If curl_cffi was blocked by Cloudflare, fall back to Playwright stealth browser
        if not html or self._is_cloudflare_challenge(html):
            logger.info("Cloudflare Turnstile challenge detected. Launching Playwright Stealth fallback...")
            try:
                html, current_base = await self._fetch_with_playwright(path)
            except Exception as e:
                logger.error(f"Playwright fallback encountered an unexpected error: {e}")
                html = None

        if not html:
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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            # 1. Fetch detail page HTML
            def _fetch_detail():
                with cffi_requests.Session(impersonate="chrome120") as s:
                    r = s.get(details_url, headers=headers, timeout=self.timeout)
                    return r.text

            html = await loop.run_in_executor(None, _fetch_detail)
            if not html:
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
                with cffi_requests.Session(impersonate="chrome120") as s:
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

    async def _fetch_with_curl_cffi(self, path: str) -> Tuple[Optional[str], str]:
        """Attempt fast HTTP fetch using curl_cffi Chrome TLS impersonation across mirror domains."""
        loop = asyncio.get_running_loop()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        seen = set()
        domains = [d for d in self.mirror_domains if not (d in seen or seen.add(d))]

        for domain in domains:
            target_url = f"{domain}{path}"
            try:
                logger.info(f"Attempting curl_cffi TLS impersonation fetch to {target_url}...")
                
                def _do_req():
                    return cffi_requests.get(target_url, headers=headers, impersonate="chrome120", timeout=self.timeout)

                resp = await loop.run_in_executor(None, _do_req)
                if resp.status_code == 200 and not self._is_cloudflare_challenge(resp.text):
                    logger.info(f"Successfully fetched search results from {domain} via curl_cffi!")
                    return resp.text, domain
                else:
                    logger.warning(f"Domain {domain} returned HTTP {resp.status_code} or Cloudflare challenge")
            except Exception as e:
                logger.warning(f"curl_cffi fetch to {domain} failed: {e}")

        return None, self.base_url

    async def _fetch_with_playwright(self, path: str) -> Tuple[Optional[str], str]:
        """Fallback Playwright stealth scraper for Cloudflare Turnstile pages."""
        target_url = f"{self.base_url}{path}"
        async with self._browser_sem:
            try:
                async with async_playwright() as p:
                    launch_options = {
                        "headless": self.headless,
                        "ignore_default_args": ["--enable-automation"],
                        "args": [
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                        ],
                    }

                    try:
                        browser = await p.chromium.launch(**launch_options, channel="chrome")
                    except Exception:
                        browser = await p.chromium.launch(**launch_options)

                    try:
                        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
                        page = await context.new_page()
                        await Stealth().apply_stealth_async(page)

                        await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                        await asyncio.sleep(2.0)

                        content = await page.content()
                        return content, self.base_url
                    finally:
                        await browser.close()
            except Exception as e:
                logger.error(f"Playwright navigation failed for {target_url}: {e}")
                return None, self.base_url


    def _is_cloudflare_challenge(self, html: str) -> bool:
        """Detect if HTML is a Cloudflare interstitial or Turnstile challenge."""
        indicators = [
            "Just a moment...",
            "Attention Required!",
            "cf-turnstile",
            "challenges.cloudflare.com",
            "Verify you are human",
            "Enable JavaScript and cookies to continue",
            "Performing security verification",
        ]
        return any(ind.lower() in html.lower() for ind in indicators)

