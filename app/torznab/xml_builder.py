import html as html_escape
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List
from app.scraper.models import TorrentItem
from .categories import get_all_categories_xml, map_cat_to_torznab


def build_caps_xml(site_name: str = "ext.to RSS / Torznab") -> str:
    """Generate Torznab capabilities XML response for t=caps request."""
    categories_snippet = get_all_categories_xml()
    safe_site_name = html_escape.escape(site_name)

    xml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server version="1.0" title="{safe_site_name}" strapline="ext.to Torznab API"/>
  <limits max="100" default="50"/>
  <searching>
    <search available="yes" supportedParams="q,cat"/>
    <tv-search available="yes" supportedParams="q,cat,season,ep"/>
    <movie-search available="yes" supportedParams="q,cat,imdbid"/>
  </searching>
  {categories_snippet}
</caps>"""
    return xml_str


def build_torznab_feed_xml(items: List[TorrentItem], title: str = "ext.to Torznab Feed") -> str:
    """Build standard Torznab XML feed containing torrent items and torznab:attr elements."""
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:torznab": "http://torznab.com/schemas/2015/feed",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
    })

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "description").text = "Torznab torrent feed generated from ext.to search"
    ET.SubElement(channel, "link").text = "https://extto.com"
    ET.SubElement(channel, "language").text = "en-us"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = item.title

        # Determine primary download link
        download_url = item.magnet_link or item.details_url
        guid_url = item.details_url or download_url

        is_permalink = "true" if (guid_url and guid_url.startswith("http")) else "false"
        ET.SubElement(entry, "guid", {"isPermaLink": is_permalink}).text = guid_url
        ET.SubElement(entry, "comments").text = guid_url
        ET.SubElement(entry, "link").text = download_url


        # Enclosure (Required by Prowlarr/Torznab parsers)
        ET.SubElement(entry, "enclosure", {
            "url": download_url,
            "length": str(max(item.size_bytes, 1024)),
            "type": "application/x-bittorrent",
        })

        # PubDate
        pub_date = item.pub_date or datetime.now(timezone.utc)
        ET.SubElement(entry, "pubDate").text = pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

        # Category
        cat_id = item.torznab_cat_id
        ET.SubElement(entry, "category").text = item.category

        # Torznab attributes
        ET.SubElement(entry, "torznab:attr", {"name": "category", "value": str(cat_id)})
        ET.SubElement(entry, "torznab:attr", {"name": "size", "value": str(max(item.size_bytes, 1024))})
        ET.SubElement(entry, "torznab:attr", {"name": "seeders", "value": str(item.seeders)})
        ET.SubElement(entry, "torznab:attr", {"name": "leechers", "value": str(item.leechers)})
        ET.SubElement(entry, "torznab:attr", {"name": "peers", "value": str(item.seeders + item.leechers)})
        ET.SubElement(entry, "torznab:attr", {"name": "downloadvolumefactor", "value": "0"})
        ET.SubElement(entry, "torznab:attr", {"name": "uploadvolumefactor", "value": "1"})

        if item.magnet_link:
            ET.SubElement(entry, "torznab:attr", {"name": "magneturl", "value": item.magnet_link})

        if item.infohash:
            ET.SubElement(entry, "torznab:attr", {"name": "infohash", "value": item.infohash})

    # Return formatted XML string
    rough_string = ET.tostring(rss, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")
