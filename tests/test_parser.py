import pytest
from app.scraper.models import TorrentItem
from app.scraper.parser import ExtToParser, parse_size_to_bytes, extract_infohash


def test_parse_size_to_bytes():
    assert parse_size_to_bytes("100 B") == 100
    assert parse_size_to_bytes("1.5 KB") == 1536
    assert parse_size_to_bytes("700 MB") == 700 * 1024 * 1024
    assert parse_size_to_bytes("2.4 GB") == int(2.4 * 1024 * 1024 * 1024)
    assert parse_size_to_bytes("1.2 TB") == int(1.2 * 1024 * 1024 * 1024 * 1024)
    assert parse_size_to_bytes("invalid") == 0


def test_extract_infohash():
    magnet = "magnet:?xt=urn:btih:b41d8cd98f00b204e9800998ecf8427e12345678&dn=Ubuntu"
    assert extract_infohash(magnet) == "B41D8CD98F00B204E9800998ECF8427E12345678"
    assert extract_infohash("http://ext.to/torrent/") is None


def test_torznab_cat_mapping():
    item_movie = TorrentItem(title="Test Movie", category="Movies")
    assert item_movie.torznab_cat_id == 2000

    item_tv = TorrentItem(title="Test Show S01E01", category="TV Shows")
    assert item_tv.torznab_cat_id == 5000

    item_music = TorrentItem(title="Album FLAC", category="Music")
    assert item_music.torznab_cat_id == 3000

    item_game = TorrentItem(title="PC Game ISO", category="Games")
    assert item_game.torznab_cat_id == 1000

    item_app = TorrentItem(title="Photoshop Pro", category="Apps")
    assert item_app.torznab_cat_id == 4000


def test_parse_search_results_html():
    sample_html = """
    <html>
      <body>
        <table class="table search-table">
          <tbody>
            <tr>
              <td class="text-left">
                <a href="/ubuntu-22-04-iso-12345/" class="torrent-title-link">Ubuntu 22.04 LTS Desktop</a>
                <div class="related-posted">in <a href="/movies/">Movies</a></div>
              </td>
              <td>3.6 GB</td>
              <td><span class="text-success">142</span></td>
              <td><span class="text-danger">12</span></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """
    parser = ExtToParser(base_url="https://extto.com")
    items = parser.parse_search_results(sample_html)

    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Ubuntu 22.04 LTS Desktop"
    assert item["details_url"] == "https://extto.com/ubuntu-22-04-iso-12345/"
    assert item["seeders"] == 142
    assert item["leechers"] == 12
    assert item["category"] == "Movies"
