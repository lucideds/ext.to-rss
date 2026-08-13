import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional
from bs4 import BeautifulSoup
from .models import TorrentItem


def parse_size_to_bytes(size_str: str) -> int:
    """Convert human readable file size string (e.g. '1.5 GB') to bytes."""
    if not size_str:
        return 0
    
    size_str = size_str.strip().upper()
    match = re.search(r"([\d\.]+)\s*([KMGTPE]?I?B|BYTES?)", size_str)
    if not match:
        return 0
    
    val = float(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        "B": 1,
        "BYTE": 1,
        "BYTES": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
        "TB": 1024**4,
        "TIB": 1024**4,
        "PB": 1024**5,
    }
    
    return int(val * multipliers.get(unit, 1))


def extract_infohash(magnet_or_url: str) -> Optional[str]:
    """Extract SHA1 infohash from magnet link or string."""
    if not magnet_or_url:
        return None
    match = re.search(r"urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", magnet_or_url, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


class ExtToParser:
    """HTML parser specifically tailored for ext.to / extto.com search results and metadata."""

    def __init__(self, base_url: str = "https://extto.com"):
        self.base_url = base_url.rstrip("/")

    def parse_tokens(self, html: str) -> tuple[str, str]:
        """Extract CSRF token and pageToken from HTML source."""
        csrf_token = ""
        page_token = ""
        
        soup = BeautifulSoup(html, "lxml")
        csrf_meta = soup.find("meta", attrs={"name": "csrf-token"})
        if csrf_meta:
            csrf_token = csrf_meta.get("content", "")

        page_token_match = re.search(r"window\.pageToken\s*=\s*[\"']([^\"']+)[\"']", html)
        if page_token_match:
            page_token = page_token_match.group(1)

        return csrf_token, page_token

    def parse_search_results(self, html: str) -> List[dict]:
        """Parse search results page HTML and extract raw torrent item dictionaries."""
        soup = BeautifulSoup(html, "lxml")
        parsed_data: List[dict] = []

        rows = soup.select("table.search-table tbody tr, table.table tbody tr")
        for row in rows:
            item_dict = self._parse_row(row)
            if item_dict:
                parsed_data.append(item_dict)

        return parsed_data

    def _parse_row(self, row) -> Optional[dict]:
        """Parse a single search result <tr> element."""
        try:
            # Title & details URL link
            title_elem = row.select_one("a.torrent-title-link, td.text-left a[href]")
            if not title_elem:
                return None

            title = title_elem.get_text(strip=True)
            details_path = title_elem.get("href", "")
            details_url = urllib.parse.urljoin(self.base_url, details_path)

            if not title or len(title) < 2:
                return None

            # Torrent ID (from data-id on magnet button or detail URL)
            torrent_id = None
            btn_elem = row.select_one("[data-id]")
            if btn_elem:
                torrent_id = int(btn_elem.get("data-id"))
            else:
                id_match = re.search(r"-(\d+)/?$", details_path)
                if id_match:
                    torrent_id = int(id_match.group(1))

            # Category extraction (exclude external user nick links)
            category = "Other"
            cat_links = row.select(".related-posted a[href], .mobile-posted-block a[href]")
            for link in cat_links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if not href.startswith("?user_nick=") and "external-user" not in link.get("class", []):
                    category = text
                    break

            # Targeted Size extraction from Size block wrapper
            size_human = "0 B"
            size_bytes = 0

            # 1. Look for add-block-wrapper containing "Size" header
            for wrapper in row.select(".add-block-wrapper"):
                hdr = wrapper.select_one(".add-block")
                if hdr and "size" in hdr.get_text().lower():
                    val_span = wrapper.select_one("span:not(.add-block)")
                    if val_span:
                        size_human = val_span.get_text(strip=True)
                        break

            # 2. Fallback to mobile info block or td cell regex
            if size_human == "0 B":
                size_td = row.select_one("td.nowrap-td")
                if size_td:
                    size_human = size_td.get_text(strip=True).replace("Size", "").strip()

            if size_human != "0 B":
                size_bytes = parse_size_to_bytes(size_human)
            
            if size_bytes == 0:
                size_bytes = 1024 * 1024  # 1 MB fallback if size missing

            # Seeders & Leechers
            seeders = 0
            leechers = 0

            seed_elem = row.select_one(".text-success, .seeders, .seeds")
            if seed_elem:
                seed_text = re.sub(r"[^\d]", "", seed_elem.get_text())
                if seed_text:
                    seeders = int(seed_text)

            leech_elem = row.select_one(".text-danger, .leechers, .leeches")
            if leech_elem:
                leech_text = re.sub(r"[^\d]", "", leech_elem.get_text())
                if leech_text:
                    leechers = int(leech_text)

            # Age / Date
            pub_date = None
            age_elem = row.select_one("span[title]")
            if age_elem and age_elem.get("title"):
                date_str = age_elem.get("title")
                try:
                    pub_date = datetime.strptime(date_str, "%d %B %Y").replace(tzinfo=timezone.utc)
                except Exception:
                    pub_date = datetime.now(timezone.utc)
            else:
                pub_date = datetime.now(timezone.utc)

            return {
                "title": title,
                "torrent_id": torrent_id,
                "details_url": details_url,
                "size_human": size_human,
                "size_bytes": size_bytes,
                "seeders": seeders,
                "leechers": leechers,
                "category": category,
                "pub_date": pub_date,
            }

        except Exception:
            return None
