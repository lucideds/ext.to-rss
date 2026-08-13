import pytest
import os
import time
import tempfile
import aiosqlite
from app.cache.db import CacheDatabase


@pytest.mark.anyio
async def test_cache_database_operations():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        cache_db = CacheDatabase(db_path=db_path, ttl_seconds=3600)
        await cache_db.init_db()

        # Query Cache
        await cache_db.set_query_cache("test_key", [{"title": "Test Torrent"}])
        cached_items = await cache_db.get_query_cache("test_key")
        assert cached_items is not None
        assert len(cached_items) == 1
        assert cached_items[0]["title"] == "Test Torrent"

        # Magnet Cache
        await cache_db.set_magnet_cache(12345, "magnet:?xt=urn:btih:ABCDEF1234567890", "ABCDEF1234567890")
        cached_magnet = await cache_db.get_magnet_cache(12345)
        assert cached_magnet is not None
        assert cached_magnet[0] == "magnet:?xt=urn:btih:ABCDEF1234567890"
        assert cached_magnet[1] == "ABCDEF1234567890"

        # Non-existent magnet cache
        non_existent = await cache_db.get_magnet_cache(99999)
        assert non_existent is None

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.anyio
async def test_cache_expiration():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        cache_db = CacheDatabase(db_path=db_path, ttl_seconds=10)
        await cache_db.init_db()

        # Insert expired entry directly
        old_time = int(time.time()) - 20
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO query_cache (query_key, json_data, created_at) VALUES (?, ?, ?)",
                ("expired_key", '[{"title": "Old Release"}]', old_time)
            )
            await db.commit()

        # Expect get_query_cache to return None because it's expired
        cached_items = await cache_db.get_query_cache("expired_key")
        assert cached_items is None

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.anyio
async def test_cache_overwrite_and_ensure_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        cache_db = CacheDatabase(db_path=db_path, ttl_seconds=3600)
        await cache_db.ensure_db()
        await cache_db.ensure_db()  # Idempotent call

        # Overwrite query cache
        await cache_db.set_query_cache("key1", [{"title": "V1"}])
        await cache_db.set_query_cache("key1", [{"title": "V2"}])
        items = await cache_db.get_query_cache("key1")
        assert items == [{"title": "V2"}]

        # Overwrite magnet cache
        await cache_db.set_magnet_cache(100, "magnet:1", "hash1")
        await cache_db.set_magnet_cache(100, "magnet:2", "hash2")
        magnet_res = await cache_db.get_magnet_cache(100)
        assert magnet_res == ("magnet:2", "hash2")

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.anyio
async def test_cache_prune_expired():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        cache_db = CacheDatabase(db_path=db_path, ttl_seconds=10)
        await cache_db.init_db()

        # Insert fresh and expired entries
        now = int(time.time())
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO query_cache (query_key, json_data, created_at) VALUES (?, ?, ?)",
                ("fresh_key", '[{"title": "Fresh"}]', now)
            )
            await db.execute(
                "INSERT INTO query_cache (query_key, json_data, created_at) VALUES (?, ?, ?)",
                ("old_key", '[{"title": "Old"}]', now - 100)
            )
            await db.commit()

        await cache_db.prune_expired()

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT query_key FROM query_cache") as cursor:
                remaining = [row[0] for row in await cursor.fetchall()]

        assert "fresh_key" in remaining
        assert "old_key" not in remaining

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

