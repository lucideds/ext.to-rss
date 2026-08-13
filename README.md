# ext.to RSS & Torznab API Generator

[![Run Tests](https://github.com/OWNER/REPO/actions/workflows/test.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/test.yml)
[![Build and Push Docker Image](https://github.com/OWNER/REPO/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/docker-publish.yml)

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

### Option A: Running with Docker (Pre-built Image from GHCR)

```bash
docker run -d \
  --name ext-to-rss \
  -p 8000:8000 \
  --restart unless-stopped \
  ghcr.io/YOUR_GITHUB_USERNAME/ext.to-rss:latest
```

### Option B: Running with Docker Compose

```bash
docker-compose up -d --build
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

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api?t=caps` | Torznab Capabilities XML |
| `GET` | `/api?t=search&q=ubuntu` | Torznab Search XML |
| `GET` | `/rss?q=ubuntu` | Standard RSS 2.0 XML Feed |
| `GET` | `/health` | Healthcheck Endpoint |
| `GET` | `/` | Web Documentation Landing Page |

---

## GitHub Actions CI/CD Workflows

- [`.github/workflows/test.yml`](file:///.github/workflows/test.yml): Runs unit & integration test suite on every `push` and `pull_request`.
- [`.github/workflows/docker-publish.yml`](file:///.github/workflows/docker-publish.yml): Automatically compiles and publishes Docker images to GitHub Container Registry (`ghcr.io`) upon pushing to `main` or tagging a release (`v1.0.0`).
