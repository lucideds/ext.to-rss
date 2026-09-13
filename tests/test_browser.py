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

