import os
import json
import time
import logging
from typing import Optional, List, Dict
import aiosqlite

logger = logging.getLogger(__name__)


class CacheDatabase:
    """Async SQLite cache for ext.to search queries and magnet link metadata."""

    def __init__(self, db_path: str = "cache.db", ttl_seconds: int = 3600):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._initialized = False

    async def init_db(self):
        """Initialize SQLite database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS query_cache (
                    query_key TEXT PRIMARY KEY,
                    json_data TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS magnet_cache (
                    torrent_id INTEGER PRIMARY KEY,
                    magnet_link TEXT NOT NULL,
                    infohash TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            await db.commit()
        self._initialized = True

    async def ensure_db(self):
        """Ensure database tables exist (idempotent, runs once per instance)."""
        if not self._initialized:
            await self.init_db()

    async def get_query_cache(self, query_key: str) -> Optional[List[Dict]]:
        """Retrieve cached query results if within TTL."""
        await self.ensure_db()
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT json_data, created_at FROM query_cache WHERE query_key = ?",
                (query_key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    json_data, created_at = row
                    if now - created_at < self.ttl_seconds:
                        logger.info(f"Cache HIT for query_key '{query_key}' ({now - created_at}s old)")
                        return json.loads(json_data)
                    else:
                        logger.info(f"Cache EXPIRED for query_key '{query_key}'")
        return None

    async def set_query_cache(self, query_key: str, items_dict: List[Dict]):
        """Save query search items to SQLite cache."""
        await self.ensure_db()
        now = int(time.time())
        json_str = json.dumps(items_dict, default=str)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO query_cache (query_key, json_data, created_at) VALUES (?, ?, ?)",
                (query_key, json_str, now)
            )
            await db.commit()

    async def get_magnet_cache(self, torrent_id: int) -> Optional[tuple[str, Optional[str]]]:
        """Retrieve cached magnet link for torrent_id."""
        await self.ensure_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT magnet_link, infohash FROM magnet_cache WHERE torrent_id = ?",
                (torrent_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1]
        return None

    async def set_magnet_cache(self, torrent_id: int, magnet_link: str, infohash: Optional[str]):
        """Cache resolved magnet link for torrent_id."""
        await self.ensure_db()
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO magnet_cache (torrent_id, magnet_link, infohash, created_at) VALUES (?, ?, ?, ?)",
                (torrent_id, magnet_link, infohash, now)
            )
            await db.commit()
