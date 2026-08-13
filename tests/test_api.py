import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_root_landing_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ext.to RSS &amp; Torznab API" in response.text or "ext.to RSS & Torznab API" in response.text


def test_caps_endpoint():
    response = client.get("/caps")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<caps>" in response.text
    assert "<searching>" in response.text


def test_torznab_api_caps():
    response = client.get("/api?t=caps")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<caps>" in response.text


def test_torznab_api_search():
    response = client.get("/api?t=search&q=ubuntu&limit=5")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<rss" in response.text
    assert "xmlns:torznab" in response.text


def test_rss_feed_endpoint():
    response = client.get("/rss?q=ubuntu")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<rss" in response.text


def test_rss_feed_category_filter():
    response = client.get("/rss?q=ubuntu&cat=movies")
    assert response.status_code == 200
    assert "<rss" in response.text

    response_id = client.get("/rss?q=ubuntu&cat=2000")
    assert response_id.status_code == 200
    assert "<rss" in response_id.text


def test_torznab_api_tvsearch_with_season_and_ep():
    response = client.get("/api?t=tvsearch&q=breaking+bad&season=1&ep=2")
    assert response.status_code == 200
    assert "<rss" in response.text


def test_torznab_api_malformed_season():
    # Should not crash with 500 error on non-numeric season
    response = client.get("/api?t=tvsearch&q=show&season=invalid_season&ep=abc")
    assert response.status_code == 200
    assert "<rss" in response.text


def test_torznab_api_category_filter():
    response = client.get("/api?t=search&q=ubuntu&cat=2000,5000")
    assert response.status_code == 200
    assert "<rss" in response.text


def test_torznab_api_imdbid():
    response = client.get("/api?t=movie&imdbid=tt1234567")
    assert response.status_code == 200
    assert "<rss" in response.text


def test_torznab_api_pagination():
    response = client.get("/api?t=search&q=ubuntu&limit=2&offset=1")
    assert response.status_code == 200
    assert "<rss" in response.text


def test_api_key_authentication():
    with patch.object(settings, "api_key", "secret_pass_123"):
        # Without key should return 401 with Torznab XML error
        res_unauth = client.get("/api?t=caps")
        assert res_unauth.status_code == 401
        assert "application/xml" in res_unauth.headers["content-type"]
        assert '<error code="100"' in res_unauth.text
        assert 'description="Invalid or missing API key."' in res_unauth.text

        # Invalid key should return 401 with Torznab XML error
        res_bad = client.get("/api?t=caps&apikey=wrongkey")
        assert res_bad.status_code == 401
        assert "application/xml" in res_bad.headers["content-type"]
        assert '<error code="100"' in res_bad.text

        # Valid key via query param apikey
        res_valid = client.get("/api?t=caps&apikey=secret_pass_123")
        assert res_valid.status_code == 200
        assert "<caps>" in res_valid.text

        # Valid key via query param api_key alias
        res_alias = client.get("/api?t=caps&api_key=secret_pass_123")
        assert res_alias.status_code == 200
        assert "<caps>" in res_alias.text

        # Valid key via X-Api-Key header
        res_header = client.get("/api?t=caps", headers={"X-Api-Key": "secret_pass_123"})
        assert res_header.status_code == 200
        assert "<caps>" in res_header.text

        # Valid key via Authorization Bearer header
        res_bearer = client.get("/api?t=caps", headers={"Authorization": "Bearer secret_pass_123"})
        assert res_bearer.status_code == 200
        assert "<caps>" in res_bearer.text

