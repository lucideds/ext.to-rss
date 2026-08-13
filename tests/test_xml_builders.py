import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from app.scraper.models import TorrentItem
from app.torznab.xml_builder import build_caps_xml, build_torznab_feed_xml
from app.rss.feed_builder import build_rss_feed_xml
from app.torznab.categories import map_cat_to_torznab, get_all_categories_xml, TORZNAB_CATEGORIES


def test_build_caps_xml():
    xml_str = build_caps_xml(site_name="Test Indexer")
    assert "<?xml" in xml_str
    root = ET.fromstring(xml_str.strip())
    assert root.tag == "caps"

    server = root.find("server")
    assert server is not None
    assert server.attrib["title"] == "Test Indexer"

    searching = root.find("searching")
    assert searching is not None
    assert searching.find("search").attrib["available"] == "yes"
    assert searching.find("tv-search").attrib["available"] == "yes"

    categories = root.find("categories")
    assert categories is not None
    cats = categories.findall("category")
    assert len(cats) > 0


def test_build_torznab_feed_xml_full_item():
    item = TorrentItem(
        title="Ubuntu 24.04 Desktop iso",
        details_url="https://extto.com/ubuntu-24-04-123/",
        magnet_link="magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678&dn=Ubuntu",
        infohash="1234567890ABCDEF1234567890ABCDEF12345678",
        size_bytes=4800000000,
        size_human="4.8 GB",
        seeders=250,
        leechers=15,
        category="Apps",
        pub_date=datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    xml_str = build_torznab_feed_xml([item], title="Test Feed")
    root = ET.fromstring(xml_str.strip())
    assert root.tag == "rss"

    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "Test Feed"

    items = channel.findall("item")
    assert len(items) == 1
    rss_item = items[0]

    assert rss_item.find("title").text == "Ubuntu 24.04 Desktop iso"
    assert rss_item.find("link").text == item.magnet_link
    assert rss_item.find("guid").text == item.details_url

    # Mandatory enclosure tag for Prowlarr
    enclosure = rss_item.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == item.magnet_link
    assert enclosure.attrib["length"] == "4800000000"
    assert enclosure.attrib["type"] == "application/x-bittorrent"

    # Torznab attributes
    attrs = {elem.attrib["name"]: elem.attrib["value"] for elem in rss_item.findall("{http://torznab.com/schemas/2015/feed}attr")}
    assert attrs["category"] == "4000"
    assert attrs["size"] == "4800000000"
    assert attrs["seeders"] == "250"
    assert attrs["leechers"] == "15"
    assert attrs["peers"] == "265"
    assert attrs["downloadvolumefactor"] == "0"
    assert attrs["uploadvolumefactor"] == "1"
    assert attrs["magneturl"] == item.magnet_link
    assert attrs["infohash"] == "1234567890ABCDEF1234567890ABCDEF12345678"


def test_build_torznab_feed_xml_fallback_urls():
    item = TorrentItem(
        title="Sample Release",
        details_url="https://extto.com/sample-123/",
        magnet_link=None,
        infohash=None,
        size_bytes=0,
        category="Other",
    )

    xml_str = build_torznab_feed_xml([item])
    root = ET.fromstring(xml_str.strip())
    rss_item = root.find("channel/item")

    # When magnet is missing, link should fallback to details_url
    assert rss_item.find("link").text == "https://extto.com/sample-123/"
    enclosure = rss_item.find("enclosure")
    assert enclosure.attrib["url"] == "https://extto.com/sample-123/"
    # Min length fallback is 1024
    assert enclosure.attrib["length"] == "1024"

    attrs = {elem.attrib["name"]: elem.attrib["value"] for elem in rss_item.findall("{http://torznab.com/schemas/2015/feed}attr")}
    assert "magneturl" not in attrs
    assert "infohash" not in attrs


def test_build_rss_feed_xml():
    item = TorrentItem(
        title="Linux Mint 21 ISO",
        details_url="https://extto.com/mint-21/",
        magnet_link="magnet:?xt=urn:btih:ABCDEF&dn=Mint",
        infohash="ABCDEF",
        size_bytes=2500000000,
        size_human="2.5 GB",
        seeders=100,
        leechers=5,
        category="Software",
    )

    xml_str = build_rss_feed_xml([item], feed_title="Custom RSS")
    root = ET.fromstring(xml_str.strip())

    channel = root.find("channel")
    assert channel.find("title").text == "Custom RSS"

    rss_item = channel.find("item")
    assert rss_item.find("title").text == "Linux Mint 21 ISO"
    assert rss_item.find("link").text == "https://extto.com/mint-21/"

    enclosure = rss_item.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == "magnet:?xt=urn:btih:ABCDEF&dn=Mint"
    assert enclosure.attrib["type"] == "application/x-bittorrent"

    desc = rss_item.find("description").text
    assert "Category: Software" in desc
    assert "Size: 2.5 GB" in desc
    assert "Seeders: 100 | Leechers: 5" in desc
    assert "Infohash: ABCDEF" in desc
    assert '<a href="magnet:?xt=urn:btih:ABCDEF&dn=Mint">Download Magnet</a>' in desc


def test_map_cat_to_torznab():
    assert map_cat_to_torznab("Movie 1080p") == 2000
    assert map_cat_to_torznab("TV Series") == 5000
    assert map_cat_to_torznab("Episode 01") == 5000
    assert map_cat_to_torznab("Audio FLAC") == 3000
    assert map_cat_to_torznab("Music MP3") == 3000
    assert map_cat_to_torznab("PC Games") == 1000
    assert map_cat_to_torznab("Software Apps") == 4000
    assert map_cat_to_torznab("Ebook PDF") == 7000
    assert map_cat_to_torznab("Anime Raw") == 5070
    assert map_cat_to_torznab("XXX Adult") == 6000
    assert map_cat_to_torznab("Random") == 8000
    assert map_cat_to_torznab("") == 8000


def test_get_all_categories_xml():
    cat_xml = get_all_categories_xml()
    assert "<categories>" in cat_xml
    assert '</categories>' in cat_xml
    root = ET.fromstring(cat_xml)
    assert root.tag == "categories"
    
    # Check parent category 2000 (Movies) and subcategory
    movie_cat = root.find("./category[@id='2000']")
    assert movie_cat is not None
    assert movie_cat.attrib["name"] == "Movies"
    subcat = movie_cat.find("./subcat[@id='2040']")
    assert subcat is not None
    assert subcat.attrib["name"] == "HD"
