"""Shared test configuration.

Ensures the FastAPI integration tests are fully hermetic:
- The SQLite cache is redirected to a throwaway temp directory.
- Any API_KEY from a developer's local .env is neutralized.
- ExtToScraper.search is mocked so no outbound network requests occur.
"""

import os
import tempfile
from datetime import datetime, timezone

_TEST_TMPDIR = tempfile.mkdtemp(prefix="extto-tests-")
os.environ["DB_PATH"] = os.path.join(_TEST_TMPDIR, "cache.db")

import pytest
from unittest.mock import AsyncMock

from app.config import settings
from app.scraper.browser import ExtToScraper
from app.scraper.models import TorrentItem

settings.api_key = None


def sample_torrent_items():
    return [
        TorrentItem(
            title="Ubuntu 24.04 LTS Desktop amd64",
            details_url="https://ext.to/ubuntu-24-04-lts-desktop-amd64-100001/",
            magnet_link="magnet:?xt=urn:btih:B41D8CD98F00B204E9800998ECF8427E12345678&dn=Ubuntu",
            infohash="B41D8CD98F00B204E9800998ECF8427E12345678",
            size_bytes=6174015488,
            size_human="5.75 GB",
            seeders=142,
            leechers=12,
            category="Applications",
            pub_date=datetime(2024, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        ),
        TorrentItem(
            title="Some Linux Movie 2024 1080p",
            details_url="https://ext.to/some-linux-movie-2024-1080p-100002/",
            magnet_link=None,
            infohash=None,
            size_bytes=2147483648,
            size_human="2.00 GB",
            seeders=55,
            leechers=3,
            category="Movies",
            pub_date=datetime(2024, 7, 15, 8, 30, 0, tzinfo=timezone.utc),
        ),
        TorrentItem(
            title="Great TV Show S01 Complete",
            details_url="https://ext.to/great-tv-show-s01-complete-100003/",
            magnet_link=None,
            infohash=None,
            size_bytes=0,
            size_human="0 B",
            seeders=0,
            leechers=0,
            category="TV Shows",
            pub_date=None,
        ),
    ]


@pytest.fixture(autouse=True)
def mock_extto_scraper(monkeypatch):
    """Replace ExtToScraper.search to prevent any outbound network traffic."""
    mock = AsyncMock(return_value=sample_torrent_items())
    monkeypatch.setattr(ExtToScraper, "search", mock)
    yield mock
