from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application Settings managed by pydantic-settings and environment variables."""

    port: int = 8000
    host: str = "0.0.0.0"
    api_key: Optional[str] = None
    ext_domain: str = "https://extto.com"
    cache_ttl_minutes: int = 60
    db_path: str = "cache.db"
    headless: bool = True
    max_magnets_per_query: int = 25
    flaresolverr_url: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
