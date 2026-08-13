import asyncio
import logging
import re
import secrets
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Query, Header, HTTPException, Request, Response, Depends, status
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.config import settings
from app.scraper.browser import ExtToScraper
from app.scraper.models import TorrentItem
from app.cache.db import CacheDatabase
from app.torznab.xml_builder import build_caps_xml, build_torznab_feed_xml, build_torznab_error_xml
from app.rss.feed_builder import build_rss_feed_xml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extto-rss")

# Globals
cache_db = CacheDatabase(db_path=settings.db_path, ttl_seconds=settings.cache_ttl_minutes * 60)
scraper = ExtToScraper(
    base_url=settings.ext_domain,
    headless=settings.headless,
    flaresolverr_url=settings.flaresolverr_url,
    cache_db=cache_db,
)


async def _periodic_prune():
    """Background task to periodically prune expired cache entries."""
    while True:
        try:
            await asyncio.sleep(1800)  # Run every 30 minutes
            await cache_db.prune_expired()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error during periodic cache pruning: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup & shutdown events."""
    logger.info("Initializing SQLite database cache...")
    await cache_db.init_db()
    prune_task = asyncio.create_task(_periodic_prune())
    yield
    logger.info("Shutting down service...")
    prune_task.cancel()
    try:
        await prune_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="ext.to Torznab & RSS Feed Generator",
    description="Bridge service allowing Prowlarr, Sonarr, Radarr, and RSS readers to query ext.to torrent indexer.",
    version="1.0.0",
    lifespan=lifespan
)


@app.exception_handler(HTTPException)
async def torznab_http_exception_handler(request: Request, exc: HTTPException):
    """Return Torznab-compliant XML errors for /api and /caps routes."""
    if request.url.path.startswith("/api") or request.url.path.startswith("/caps"):
        code = 100 if exc.status_code == status.HTTP_401_UNAUTHORIZED else 200
        error_xml = build_torznab_error_xml(code=code, description=str(exc.detail))
        return Response(content=error_xml, status_code=exc.status_code, media_type="application/xml")
    return Response(
        content=f'{{"detail":"{exc.detail}"}}',
        status_code=exc.status_code,
        media_type="application/json"
    )


@app.exception_handler(Exception)
async def torznab_generic_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler returning Torznab XML for /api routes."""
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    if request.url.path.startswith("/api") or request.url.path.startswith("/caps"):
        error_xml = build_torznab_error_xml(code=999, description="Internal Server Error")
        return Response(content=error_xml, status_code=500, media_type="application/xml")
    return Response(
        content='{"detail":"Internal Server Error"}',
        status_code=500,
        media_type="application/json"
    )


def verify_api_key(
    apikey: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Verify optional API key parameter or header if configured in settings."""
    if not settings.api_key:
        return

    provided_key = apikey or api_key or x_api_key
    if not provided_key and authorization:
        if authorization.lower().startswith("bearer "):
            provided_key = authorization[7:].strip()
        else:
            provided_key = authorization.strip()

    if not provided_key or not secrets.compare_digest(provided_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key."
        )


@app.get("/health", tags=["Health"])
async def health_check():
    """Service health check endpoint with database verification."""
    db_ok = await cache_db.check_health()
    status_str = "ok" if db_ok else "degraded"
    return {
        "status": status_str,
        "database": "connected" if db_ok else "unreachable",
        "domain": settings.ext_domain
    }


@app.get("/caps", response_class=Response, tags=["Torznab"])
async def caps_endpoint(_: None = Depends(verify_api_key)):
    """Torznab capabilities XML endpoint."""
    xml_content = build_caps_xml()
    return Response(content=xml_content, media_type="application/xml")


@app.get("/api", response_class=Response, tags=["Torznab"])
@app.get("/api/api", response_class=Response, tags=["Torznab"])
async def torznab_api(
    t: str = Query("search", description="Torznab search type (caps, search, tvsearch, movie)"),
    q: Optional[str] = Query(None, description="Search query string"),
    cat: Optional[str] = Query(None, description="Torznab category IDs comma separated"),
    limit: Optional[int] = Query(50, description="Results limit"),
    offset: Optional[int] = Query(0, description="Results offset"),
    apikey: Optional[str] = Query(None, description="API key"),
    api_key: Optional[str] = Query(None, description="API key alias"),
    season: Optional[str] = Query(None, description="TV Season"),
    ep: Optional[str] = Query(None, description="TV Episode"),
    imdbid: Optional[str] = Query(None, description="IMDb ID"),
    _: None = Depends(verify_api_key)
):
    """Main Torznab API endpoint for Prowlarr/Sonarr/Radarr integration."""
    t_lower = t.lower()

    if t_lower == "caps":
        xml_content = build_caps_xml()
        return Response(content=xml_content, media_type="application/xml")

    # Build search query string
    search_query = q or ""
    if imdbid:
        search_query = imdbid if not search_query else f"{search_query} {imdbid}"

    if season:
        try:
            clean_season = re.sub(r"[^\d]", "", str(season))
            if clean_season:
                season_str = f"S{int(clean_season):02d}"
                if ep:
                    clean_ep = re.sub(r"[^\d]", "", str(ep))
                    if clean_ep:
                        season_str += f"E{int(clean_ep):02d}"
                search_query = f"{search_query} {season_str}".strip()
        except ValueError:
            pass

    if not search_query:
        # If query is empty, default search to current year
        search_query = str(datetime.now().year)

    # Unified search query cache key
    cache_key = f"query:{search_query}"

    # Check cache first
    cached_data = await cache_db.get_query_cache(cache_key)
    if cached_data:
        items = [TorrentItem(**d) for d in cached_data]
    else:
        # Fetch live via scraper with error handling
        try:
            items = await scraper.search(search_query, max_magnets=settings.max_magnets_per_query)
            # Store in cache
            dict_items = [item.model_dump() for item in items]
            await cache_db.set_query_cache(cache_key, dict_items)
        except Exception as e:
            logger.error(f"Scraper error during search query '{search_query}': {e}")
            items = []

    # Filter by Torznab categories if requested
    if cat:
        requested_cats = set()
        for c in cat.split(","):
            c_clean = c.strip()
            if c_clean.isdigit():
                requested_cats.add(int(c_clean))
        if requested_cats:
            items = [
                item for item in items
                if item.torznab_cat_id in requested_cats or (item.torznab_cat_id // 1000 * 1000) in requested_cats
            ]

    # Slice limit/offset
    sliced_items = items[offset : offset + limit] if limit else items

    # Build Torznab XML
    xml_content = build_torznab_feed_xml(sliced_items, title=f"ext.to Torznab - {search_query}")
    return Response(content=xml_content, media_type="application/xml")


@app.get("/rss", response_class=Response, tags=["RSS"])
@app.get("/feed.xml", response_class=Response, tags=["RSS"])
async def rss_feed(
    q: Optional[str] = Query("latest", description="Search query"),
    cat: Optional[str] = Query(None, description="Category filter"),
    apikey: Optional[str] = Query(None, description="API Key"),
    api_key: Optional[str] = Query(None, description="API Key alias"),
    _: None = Depends(verify_api_key)
):
    """Standard RSS 2.0 feed XML endpoint for feed readers."""
    search_query = q or "latest"
    cache_key = f"query:{search_query}"

    cached_data = await cache_db.get_query_cache(cache_key)
    if cached_data:
        items = [TorrentItem(**d) for d in cached_data]
    else:
        try:
            items = await scraper.search(search_query, max_magnets=settings.max_magnets_per_query)
            dict_items = [item.model_dump() for item in items]
            await cache_db.set_query_cache(cache_key, dict_items)
        except Exception as e:
            logger.error(f"Scraper error during RSS query '{search_query}': {e}")
            items = []

    # Filter by category string or Torznab cat ID if provided
    if cat:
        cat_lower = cat.strip().lower()
        items = [
            item for item in items
            if cat_lower in item.category.lower() or cat_lower in str(item.torznab_cat_id)
        ]

    xml_content = build_rss_feed_xml(items, feed_title=f"ext.to RSS Feed - {search_query}")
    return Response(content=xml_content, media_type="application/xml")




@app.get("/", response_class=HTMLResponse, tags=["Web"])
async def root_index():
    """Simple Web Landing Page with setup documentation."""
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>ext.to RSS & Torznab API</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #333; }
        h1 { color: #0284c7; }
        code { background: #f1f5f9; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.9em; }
        pre { background: #f8fafc; border: 1px solid #e2e8f0; padding: 1rem; border-radius: 8px; overflow-x: auto; }
        .badge { background: #0284c7; color: white; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.8em; font-weight: bold; }
    </style>
</head>
<body>
    <h1>ext.to RSS & Torznab API <span class="badge">Active</span></h1>
    <p>This service bridges <strong>ext.to</strong> torrent indexer to standard <strong>Torznab API</strong> (Prowlarr / Sonarr / Radarr) and standard <strong>RSS 2.0 XML</strong> feeds.</p>

    <h2>Endpoints</h2>
    <ul>
        <li><code>GET /api?t=caps</code> - Torznab Capabilities XML</li>
        <li><code>GET /api?t=search&q=ubuntu</code> - Torznab Search</li>
        <li><code>GET /rss?q=ubuntu</code> - Standard RSS 2.0 XML Feed</li>
        <li><code>GET /health</code> - Health Check</li>
    </ul>

    <h2>Prowlarr Integration Setup</h2>
    <ol>
        <li>Open Prowlarr &gt; <strong>Indexers</strong> &gt; <strong>Add Indexer</strong></li>
        <li>Select <strong>Generic Torznab</strong></li>
        <li>Set Name: <code>ext.to</code></li>
        <li>Set URL: <code>http://YOUR_SERVER_IP:8000/api</code></li>
        <li>Set API Key: (Match API_KEY in your .env if enabled)</li>
    </ol>
</body>
</html>"""
    return HTMLResponse(content=html_content)
