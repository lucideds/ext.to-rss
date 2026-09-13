FROM python:3.11-slim

# wget is required by the container HEALTHCHECK.
# fontconfig + fonts-*: Chromium's Skia backend aborts the whole browser process
# ("FATAL:third_party/skia/src/ports/SkFontMgr_FontConfigInterface.cpp Not
# implemented.") when the image has no fonts at all, which silently kills the
# Playwright fallback and leaves core dumps behind. Playwright's --with-deps does
# not always pull these in, so install them explicitly.
# xvfb: allows HEADLESS=false to drive a headed browser (Cloudflare managed
# challenges are far more likely to clear in a headed browser).
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-unifont \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Browsers must live OUTSIDE the build user's HOME, otherwise the non-root
# runtime user (appuser) cannot find them and every Playwright launch fails with
# "Executable doesn't exist at /home/appuser/.cache/ms-playwright/...".
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy requirements and install runtime dependencies + Chromium binaries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    patchright install --with-deps chromium && \
    chmod -R a+rX /ms-playwright

# Copy application source code
COPY . .
RUN mkdir -p /app/data && \
    groupadd -r appuser && useradd -r -m -d /home/appuser -g appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

# Chromium's crashpad handler needs a writable HOME ("--database is required"
# otherwise kills the headed browser), so make sure one exists.
ENV HOME=/home/appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run Uvicorn ASGI server (HOST/PORT env vars configurable).
# HEADLESS=false wraps the server in Xvfb so the stealth browser can run headed.
CMD ["sh", "-c", "if [ \"${HEADLESS:-true}\" = \"false\" ]; then exec xvfb-run -a uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}; else exec uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}; fi"]
