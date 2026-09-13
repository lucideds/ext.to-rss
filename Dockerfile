FROM python:3.11-slim

# wget is required by the container HEALTHCHECK; Playwright installs its own
# Chromium system dependencies via `install --with-deps`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install runtime dependencies + Chromium binaries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

# Copy application source code
COPY . .
RUN mkdir -p /app/data && \
    groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run Uvicorn ASGI server (HOST/PORT env vars configurable)
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
