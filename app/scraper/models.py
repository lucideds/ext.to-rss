from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.torznab.categories import map_cat_to_torznab


class TorrentItem(BaseModel):
    """Represents a parsed torrent item from ext.to search results."""

    title: str = Field(..., description="Torrent title")
    details_url: Optional[str] = Field(None, description="Full URL to ext.to details page")
    magnet_link: Optional[str] = Field(None, description="Magnet URI link")
    infohash: Optional[str] = Field(None, description="SHA1 infohash")
    size_bytes: int = Field(0, description="Size in bytes")
    size_human: str = Field("0 B", description="Human readable size (e.g., '1.5 GB')")
    seeders: int = Field(0, description="Number of seeders")
    leechers: int = Field(0, description="Number of leechers")
    category: str = Field("Other", description="Ext.to category name")
    pub_date: Optional[datetime] = Field(None, description="Publication / upload date")
    uploader: Optional[str] = Field(None, description="Uploader username if available")

    @property
    def torznab_cat_id(self) -> int:
        """Map ext.to category name to standard Torznab category ID."""
        return map_cat_to_torznab(self.category)

