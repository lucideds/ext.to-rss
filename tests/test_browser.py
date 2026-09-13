import pytest
import hashlib
from unittest.mock import MagicMock, patch
from app.scraper.browser import ExtToScraper


def test_is_cloudflare_challenge():
    scraper = ExtToScraper()

    # Cloudflare challenge samples
    assert scraper._is_cloudflare_challenge("<html><title>Just a moment...</title></html>") is True
    assert scraper._is_cloudflare_challenge("<div class='cf-turnstile'></div>") is True
    assert scraper._is_cloudflare_challenge("<script src='https://challenges.cloudflare.com/turnstile'></script>") is True
    assert scraper._is_cloudflare_challenge("<p>Verify you are human</p>") is True
    assert scraper._is_cloudflare_challenge("<h1>Attention Required!</h1>") is True

    # Clean HTML samples
    assert scraper._is_cloudflare_challenge("<html><body><table class='search-table'></table></body></html>") is False
    assert scraper._is_cloudflare_challenge("<div>Welcome to ext.to search results</div>") is False


@pytest.mark.anyio
async def test_resolve_magnet_for_item_success():
    scraper = ExtToScraper(base_url="https://ext.to")

    html_response = """
    <html>
      <head>
        <meta name="csrf-token" content="mock_csrf_token_123">
        <script>window.pageToken = 'mock_page_token_456';</script>
      </head>
      <body>Detail page</body>
    </html>
    """

    api_json_response = {
        "success": True,
        "url": "magnet:?xt=urn:btih:9876543210FEDCBA9876543210FEDCBA98765432&dn=Test"
    }

    mock_get_resp = MagicMock()
    mock_get_resp.text = html_response

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = api_json_response

    with patch("curl_cffi.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = mock_get_resp
        mock_session.post.return_value = mock_post_resp

        magnet, infohash = await scraper.resolve_magnet_for_item(
            details_url="https://ext.to/test-torrent-999/",
            torrent_id=999
        )

        assert magnet == "magnet:?xt=urn:btih:9876543210FEDCBA9876543210FEDCBA98765432&dn=Test"
        assert infohash == "9876543210FEDCBA9876543210FEDCBA98765432"

        # Verify POST payload contained expected HMAC structure
        assert mock_session.post.called
        post_args, post_kwargs = mock_session.post.call_args
        post_data = post_kwargs.get("data", {})
        assert post_data["torrent_id"] == 999
        assert post_data["download_type"] == "magnet"
        assert post_data["sessid"] == "mock_csrf_token_123"
        assert len(post_data["hmac"]) == 64  # SHA256 hex digest length


@pytest.mark.anyio
async def test_resolve_magnet_for_item_failure():
    scraper = ExtToScraper(base_url="https://ext.to")

    # Return empty HTML
    mock_get_resp = MagicMock()
    mock_get_resp.text = ""

    with patch("curl_cffi.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = mock_get_resp

        magnet, infohash = await scraper.resolve_magnet_for_item(
            details_url="https://ext.to/test-torrent-999/",
            torrent_id=999
        )

        assert magnet is None
        assert infohash is None


@pytest.mark.anyio
async def test_fetch_with_playwright_exception_resilience():
    scraper = ExtToScraper(base_url="https://ext.to")

    with patch("app.scraper.browser.async_playwright") as mock_playwright:
        mock_playwright.side_effect = Exception("Chromium launch timeout")
        content, base = await scraper._fetch_with_playwright("/browse/?q=test")
        assert content is None
        assert base == "https://ext.to"


# --- regression tests: challenge detection precision -------------------------


def test_turnstile_script_on_healthy_page_is_not_a_challenge():
    """Healthy pages embed Turnstile scripts; they must not be rejected."""
    scraper = ExtToScraper()

    healthy = """
    <html><head><title>Young Sheldon S06E04 - ext.to</title>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
    </head><body>
      <table class="torrent-table"><tbody><tr><td><a href="/torrent/young-sheldon-123/">x</a></td></tr></tbody></table>
    </body></html>
    """
    assert scraper._is_cloudflare_challenge(healthy) is False
    assert scraper._is_cloudflare_challenge(None) is False
    assert scraper._is_cloudflare_challenge("") is False


def test_interstitial_markers_are_challenges():
    scraper = ExtToScraper()

    assert scraper._is_cloudflare_challenge("<title>Just a moment...</title>") is True
    assert scraper._is_cloudflare_challenge("<div id='challenge-error-text'>x</div>") is True
    assert scraper._is_cloudflare_challenge("<script>window._cf_chl_opt={cvId:'3'}</script>") is True
    assert scraper._is_cloudflare_challenge("<p>Performing security verification</p>") is True
    # Block page with no page content at all
    assert scraper._is_cloudflare_challenge("<script src='https://challenges.cloudflare.com/x.js'></script>") is True


def test_real_results_page_with_cf_jsd_script_is_not_a_challenge():
    """Every Cloudflare-fronted page loads /cdn-cgi/challenge-platform/.../jsd/main.js.

    A page that contains that script *and* real search results must be accepted
    (this exact false positive kept the scraper clicking a widget forever).
    """
    scraper = ExtToScraper()
    real_page = (
        "<html><head><title>Young Sheldon S06E04 Torrent (36 results) - EXT Torrents</title>"
        "<script>(function(){var a=document.createElement('script');"
        "a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';"
        "document.getElementsByTagName('head')[0].appendChild(a);})();</script></head>"
        "<body><table class='table table-striped table-hover search-table'><tbody>"
        "<tr><td><a class='torrent-title-link' href='/young-sheldon-s06e04-9104684/'>Young Sheldon S06E04</a></td></tr>"
        "</tbody></table></body></html>"
    )
    assert scraper._is_cloudflare_challenge(real_page) is False

    # …but the interstitial itself (no results) still counts.
    interstitial = "<html><head><title>Just a moment...</title></head><body>Performing security verification</body></html>"
    assert scraper._is_cloudflare_challenge(interstitial) is True


# --- regression tests: session (clearance cookie) handling -------------------


@pytest.mark.anyio
async def test_session_state_roundtrip(tmp_path):
    from app.cache.db import CacheDatabase

    db = CacheDatabase(db_path=str(tmp_path / "cache.db"), ttl_seconds=60, session_ttl_seconds=600)
    await db.set_session_state("cf_session", {"cookies": {"cf_clearance": "abc"}, "browser_user_agent": "UA/1"})
    state = await db.get_session_state("cf_session")
    assert state is not None
    assert state["cookies"]["cf_clearance"] == "abc"
    assert state["browser_user_agent"] == "UA/1"

    # Expired session state must not be returned
    expired = CacheDatabase(db_path=str(tmp_path / "cache.db"), ttl_seconds=60, session_ttl_seconds=-1)
    assert await expired.get_session_state("cf_session") is None


@pytest.mark.anyio
async def test_harvested_cookies_are_reused_by_curl_cffi_path(tmp_path):
    from app.cache.db import CacheDatabase

    db = CacheDatabase(db_path=str(tmp_path / "cache.db"), ttl_seconds=60, session_ttl_seconds=600)
    scraper = ExtToScraper(cache_db=db)
    scraper._browser_user_agent = "UA/2"

    await scraper._store_session_state({"cf_clearance": "tok", "some_analytics": "drop-me"})
    assert scraper.filtered_cookie_header == "cf_clearance=tok"
    assert scraper.effective_user_agent == "UA/2"

    headers = scraper._request_headers()
    assert headers["Cookie"] == "cf_clearance=tok"
    assert headers["User-Agent"] == "UA/2"

    # A fresh scraper (e.g. after a container restart) picks the cookie back up.
    fresh = ExtToScraper(cache_db=db)
    await fresh._load_session_state()
    assert fresh.filtered_cookie_header == "cf_clearance=tok"
    assert fresh.effective_user_agent == "UA/2"


def test_manual_cf_clearance_is_used_immediately():
    scraper = ExtToScraper(cf_clearance="manual-token")
    assert scraper.filtered_cookie_header == "cf_clearance=manual-token"
    assert scraper._session_loaded is True


def test_launch_options_include_proxy_and_channel():
    scraper = ExtToScraper(proxy_url="http://127.0.0.1:8080", browser_channel="chrome")
    options = scraper._launch_options()
    assert options["proxy"] == {"server": "http://127.0.0.1:8080"}
    assert options["channel"] == "chrome"
    assert "--disable-dev-shm-usage" in options["args"]

    plain = ExtToScraper()._launch_options()
    assert "proxy" not in plain and "channel" not in plain


# --- regression tests: challenge wait loop -----------------------------------


class _FakePage:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = 0

    async def content(self):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        return body


@pytest.mark.anyio
async def test_await_challenge_resolution_returns_cleared_page():
    scraper = ExtToScraper(challenge_wait_seconds=5)
    page = _FakePage([
        "<title>Just a moment...</title>",
        "<title>Just a moment...</title>",
        "<table class='torrent-table'></table>",
    ])
    html = await scraper._await_challenge_resolution(page)
    assert html is not None and "torrent-table" in html
    assert page.calls == 3


@pytest.mark.anyio
async def test_await_challenge_resolution_gives_up_after_timeout():
    scraper = ExtToScraper(challenge_wait_seconds=1)
    page = _FakePage(["<title>Just a moment...</title>"])
    html = await scraper._await_challenge_resolution(page)
    assert html is not None and scraper._is_cloudflare_challenge(html) is True


# --- regression tests: Turnstile widget click --------------------------------


class _FakeMouse:
    def __init__(self):
        self.events = []

    async def move(self, x, y):
        self.events.append(("move", x, y))

    async def click(self, x, y):
        self.events.append(("click", x, y))


class _FakeElement:
    def __init__(self, box):
        self._box = box

    async def bounding_box(self):
        return self._box


class _FakeFrame:
    def __init__(self, url, box):
        self.url = url
        self._box = box

    async def frame_element(self):
        return _FakeElement(self._box)


class _FakePageWithFrames:
    """Interstitial until a click is seen, then the real page."""

    def __init__(self, frames):
        self.frames = frames
        self.mouse = _FakeMouse()
        self.cleared = False

    async def content(self):
        if self.mouse.events and any(e[0] == "click" for e in self.mouse.events):
            self.cleared = True
            return "<table class='search-table'><tbody><tr><td>result</td></tr></tbody></table>"
        return "<title>Just a moment...</title>"


@pytest.mark.anyio
async def test_turnstile_widget_is_clicked_to_clear_challenge():
    scraper = ExtToScraper(challenge_wait_seconds=10)
    frame = _FakeFrame("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x", {"x": 350, "y": 300, "width": 300, "height": 65})
    page = _FakePageWithFrames([frame])

    html = await scraper._await_challenge_resolution(page)
    clicks = [e for e in page.mouse.events if e[0] == "click"]
    assert len(clicks) == 1, "widget should be clicked exactly once"
    # first attempt targets the widget centre (mouse coordinates, not page coords)
    assert abs(clicks[0][1] - (350 + 150)) < 1 and abs(clicks[0][2] - (300 + 32.5)) < 1
    assert html is not None and not scraper._is_cloudflare_challenge(html)


@pytest.mark.anyio
async def test_widget_click_disabled_does_not_click():
    scraper = ExtToScraper(challenge_wait_seconds=1, solve_challenge=False)
    frame = _FakeFrame("https://challenges.cloudflare.com/x", {"x": 10, "y": 10, "width": 100, "height": 50})
    page = _FakePageWithFrames([frame])
    await scraper._await_challenge_resolution(page)
    assert [e for e in page.mouse.events if e[0] == "click"] == []


@pytest.mark.anyio
async def test_widget_clicks_are_capped():
    """Hammering the widget escalates the challenge - count must stay bounded."""
    scraper = ExtToScraper(challenge_wait_seconds=1, max_solve_clicks=1, solve_click_gap_seconds=0)
    frame = _FakeFrame("https://challenges.cloudflare.com/x", {"x": 0, "y": 0, "width": 100, "height": 50})

    class _NeverClears(_FakePageWithFrames):
        async def content(self):
            return "<title>Just a moment...</title>"

    page = _NeverClears([frame])
    await scraper._await_challenge_resolution(page)
    assert len([e for e in page.mouse.events if e[0] == "click"]) == 1


def test_parser_keeps_word_spacing_in_spanned_titles():
    """ext.to wraps each word in <span>; titles must not run together."""
    from app.scraper.parser import ExtToParser

    html = """
    <table class="search-table"><tbody><tr>
      <td class="text-left">
        <a class="torrent-title-link" href="/young-sheldon-s06e04-720p-hdtv-x264-syncopy-eztv-9104684/">
          <b><span>Young</span> <span>Sheldon</span> <span>S06E04</span> 720p HDTV x264-SYNCOPY EZTV</b>
        </a>
        <div class="related-posted">Posted by <a href="?user_nick=jajaja">jajaja</a> in <a href="/tv/">TV</a></div>
        <span class="add-block-wrapper"><span class="add-block">Size</span><span>328.78 MB</span></span>
      </td>
      <td><span class="text-success">310</span></td>
      <td><span class="text-danger">157</span></td>
      <td><span title="21 October 2022">3 years ago</span></td>
    </tr></tbody></table>
    """
    items = ExtToParser().parse_search_results(html)
    assert len(items) == 1
    assert items[0]["title"] == "Young Sheldon S06E04 720p HDTV x264-SYNCOPY EZTV"
    assert items[0]["torrent_id"] == 9104684
    assert items[0]["details_url"].endswith("-9104684/")

