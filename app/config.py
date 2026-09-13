from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application Settings managed by pydantic-settings and environment variables."""

    port: int = 8000
    host: str = "0.0.0.0"
    api_key: Optional[str] = None
    ext_domain: str = "https://ext.to"
    cache_ttl_minutes: int = 60
    db_path: str = "cache.db"
    headless: bool = True
    max_magnets_per_query: int = 25
    flaresolverr_url: Optional[str] = None

    # --- Cloudflare / browser behaviour -------------------------------------
    # HTTP(S) proxy used by BOTH curl_cffi and Playwright. A residential or
    # out-of-region egress is usually required when Cloudflare hard-blocks the
    # host IP (challenge loops that never issue `cf_clearance`).
    proxy_url: Optional[str] = None
    # Manual clearance cookie, e.g. copied from a browser that already passed the
    # challenge on the SAME egress IP (cf_clearance is bound to IP + User-Agent).
    cf_clearance: Optional[str] = None
    # User-Agent used by curl_cffi and injected into the browser context. Keep it
    # consistent with `impersonate` so the TLS fingerprint matches the UA.
    user_agent: Optional[str] = None
    # curl_cffi TLS impersonation target for the fast path.
    impersonate: str = "chrome120"
    # How long to keep polling a Playwright page for the challenge to clear.
    challenge_wait_seconds: int = 45
    # How long a harvested `cf_clearance` cookie stays usable in the DB cache.
    cookie_ttl_minutes: int = 180
    # Optional Playwright browser channel ("chrome", "chromium", "msedge").
    browser_channel: Optional[str] = None
    # Click the Cloudflare "Verify you are human" checkbox when the challenge is
    # presented (ext.to's managed challenge never clears without that click).
    solve_challenge: bool = True
    # Cap and space out widget clicks: hammering the challenge makes Cloudflare
    # escalate to one that never clears, so a small number of slow clicks is best.
    max_solve_clicks: int = 2
    solve_click_gap_seconds: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
