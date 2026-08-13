import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
        # Without key should return 401
        res_unauth = client.get("/api?t=caps")
        assert res_unauth.status_code == 401
        assert res_unauth.json()["detail"] == "Invalid or missing API key."

        # Invalid key should return 401
        res_bad = client.get("/api?t=caps&apikey=wrongkey")
        assert res_bad.status_code == 401

        # Valid key should succeed
        res_valid = client.get("/api?t=caps&apikey=secret_pass_123")
        assert res_valid.status_code == 200
        assert "<caps>" in res_valid.text
