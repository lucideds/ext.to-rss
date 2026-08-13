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
    scraper = ExtToScraper(base_url="https://extto.com")

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
            details_url="https://extto.com/test-torrent-999/",
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
    scraper = ExtToScraper(base_url="https://extto.com")

    # Return empty HTML
    mock_get_resp = MagicMock()
    mock_get_resp.text = ""

    with patch("curl_cffi.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = mock_get_resp

        magnet, infohash = await scraper.resolve_magnet_for_item(
            details_url="https://extto.com/test-torrent-999/",
            torrent_id=999
        )

        assert magnet is None
        assert infohash is None


@pytest.mark.anyio
async def test_fetch_with_playwright_exception_resilience():
    scraper = ExtToScraper(base_url="https://extto.com")

    with patch("app.scraper.browser.async_playwright") as mock_playwright:
        mock_playwright.side_effect = Exception("Chromium launch timeout")
        content, base = await scraper._fetch_with_playwright("/browse/?q=test")
        assert content is None
        assert base == "https://extto.com"

