# ext.to RSS & Torznab API Generator

[![Run Tests](https://github.com/lucideds/ext.to-rss/actions/workflows/test.yml/badge.svg)](https://github.com/lucideds/ext.to-rss/actions/workflows/test.yml)
[![Build and Push Docker Image](https://github.com/lucideds/ext.to-rss/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/lucideds/ext.to-rss/actions/workflows/docker-publish.yml)

Self-contained proxy service that scrapes **ext.to** (bypassing Cloudflare protections) and exposes standard **Torznab API** endpoints for Prowlarr/Sonarr/Radarr and **RSS 2.0 XML** feeds for RSS aggregators.

---

## Features

- **Prowlarr / Sonarr / Radarr Integration**: Full Torznab API implementation (`t=caps`, `t=search`, `t=tvsearch`, `t=movie`).
- **Cloudflare & Anti-Bot Bypass**: High-performance `curl_cffi` Chrome TLS impersonation engine with automatic Playwright stealth browser fallback.
- **HMAC SHA256 Magnet & Infohash Resolution**: Automatically resolves full magnet URIs and 40-character SHA1 infohashes.
- **SQLite Persistent Caching**: Caches search queries and magnet metadata to prevent IP bans and minimize request overhead.
- **Category Mapping**: Maps ext.to categories to standard Torznab category IDs (Movies=2000, TV=5000, Books=7000, Audio=3000, etc.).
- **CI/CD & Docker Registry Ready**: Automated GitHub Actions testing and container image publishing to GitHub Container Registry (`ghcr.io`).

---

## Quick Start

### Option A: Running with Docker Compose (Recommended)

1. Create a `docker-compose.yml` file (or use the one included in this repository):

```yaml
services:
  ext-to-rss:
    image: ghcr.io/lucideds/ext.to-rss:latest
    container_name: ext-to-rss
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - PORT=8000
      - HOST=0.0.0.0
      - EXT_DOMAIN=https://ext.to
      - DB_PATH=/app/data/cache.db
      - CACHE_TTL_MINUTES=60
      - HEADLESS=true
      - MAX_MAGNETS_PER_QUERY=25
      # - API_KEY=your_secret_api_key
      # - FLARESOLVERR_URL=http://flaresolverr:8191/v1
    volumes:
      - ./data:/app/data
```

2. Start the service:

```bash
# Start in background
docker compose up -d

# View live logs
docker compose logs -f

# Stop the service
docker compose down
```

---

### Environment Variables

Configure the service via environment variables in `docker-compose.yml` or a `.env` file:

| Variable                | Type    | Default                                     | Description                                                                            |
| :---------------------- | :------ | :------------------------------------------ | :------------------------------------------------------------------------------------- |
| `PORT`                  | Integer | `8000`                                      | Port for the Uvicorn HTTP server.                                                      |
| `HOST`                  | String  | `0.0.0.0`                                   | Host IP address to bind to.                                                            |
| `API_KEY`               | String  | _(Optional / None)_                         | Secret API key to require on `/api` and `/rss` requests (via `?apikey=...` or header). |
| `EXT_DOMAIN`            | String  | `https://ext.to`                            | ext.to mirror domain (`https://ext.to`, `https://extto.com`, `https://ext2.to`).       |
| `DB_PATH`               | String  | `cache.db` (`/app/data/cache.db` in Docker) | File path for persistent SQLite cache.                                                 |
| `CACHE_TTL_MINUTES`     | Integer | `60`                                        | Duration (in minutes) search results and resolved magnets remain cached.               |
| `HEADLESS`              | Boolean | `true`                                      | Run Playwright Chromium in headless mode.                                              |
| `MAX_MAGNETS_PER_QUERY` | Integer | `25`                                        | Max number of magnet links to dynamically resolve per search query.                    |
| `FLARESOLVERR_URL`      | String  | _(Optional / None)_                         | URL of an external FlareSolverr instance if used for Cloudflare clearance.             |

---

### Option B: Running with Docker CLI (Pre-built Image)

```bash
docker run -d \
  --name ext-to-rss \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e DB_PATH=/app/data/cache.db \
  -e EXT_DOMAIN=https://ext.to \
  --restart unless-stopped \
  ghcr.io/lucideds/ext.to-rss:latest
```

---

### Option C: Local Python Setup

1. **Clone & Setup Virtual Environment**:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

2. **Run Server**:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Prowlarr Setup Instructions

1. Open **Prowlarr** &gt; **Indexers** &gt; **Add Indexer**.
2. Search and select **Generic Torznab**.
3. Fill out the configuration fields:
   - **Name**: `ext.to`
   - **URL**: `http://<YOUR_SERVER_IP>:8000` (or `http://<YOUR_SERVER_IP>:8000/api`)
   - **API Key**: (If `API_KEY` is set in your `.env`, enter it here; otherwise leave blank)
4. Click **Test** and **Save**.

---

## API Endpoints

| Method | Endpoint                 | Description                    |
| :----- | :----------------------- | :----------------------------- |
| `GET`  | `/api?t=caps`            | Torznab Capabilities XML       |
| `GET`  | `/api?t=search&q=ubuntu` | Torznab Search XML             |
| `GET`  | `/rss?q=ubuntu`          | Standard RSS 2.0 XML Feed      |
| `GET`  | `/health`                | Healthcheck Endpoint           |
| `GET`  | `/`                      | Web Documentation Landing Page |
