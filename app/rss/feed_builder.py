from datetime import datetime, timezone
import html as html_escape
import xml.etree.ElementTree as ET
from typing import List
from app.scraper.models import TorrentItem


def build_rss_feed_xml(items: List[TorrentItem], feed_title: str = "ext.to RSS Feed") -> str:
    """Build standard RSS 2.0 XML feed with magnet enclosures."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = "https://ext.to"
    ET.SubElement(channel, "description").text = "Latest torrent feeds scraped from ext.to"
    ET.SubElement(channel, "language").text = "en-us"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = item.title

        if item.details_url:
            ET.SubElement(entry, "link").text = item.details_url
            ET.SubElement(entry, "guid", {"isPermaLink": "true"}).text = item.details_url

        if item.magnet_link:
            ET.SubElement(entry, "enclosure", {
                "url": item.magnet_link,
                "length": str(item.size_bytes),
                "type": "application/x-bittorrent",
            })

        # Description with metadata summary
        desc_text = (
            f"Category: {item.category}<br/>"
            f"Size: {item.size_human}<br/>"
            f"Seeders: {item.seeders} | Leechers: {item.leechers}<br/>"
        )
        if item.infohash:
            desc_text += f"Infohash: {item.infohash}<br/>"
        if item.magnet_link:
            safe_magnet = html_escape.escape(item.magnet_link, quote=True)
            desc_text += f'<a href="{safe_magnet}">Download Magnet</a>'

        ET.SubElement(entry, "description").text = desc_text

        # Category
        ET.SubElement(entry, "category").text = item.category

        # PubDate
        pub_date = item.pub_date or datetime.now(timezone.utc)
        ET.SubElement(entry, "pubDate").text = pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Return serialized XML string
    return ET.tostring(rss, encoding="UTF-8", xml_declaration=True).decode("utf-8")
