import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
