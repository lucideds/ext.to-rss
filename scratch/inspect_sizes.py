import sys
sys.path.insert(0, ".")

from bs4 import BeautifulSoup
from curl_cffi import requests
from app.scraper.parser import ExtToParser

r = requests.get("https://extto.com/browse/?q=last+of+us+S01E02", impersonate="chrome120")
soup = BeautifulSoup(r.text, "lxml")
parser = ExtToParser()

rows = soup.select("table.search-table tbody tr, table.table tbody tr")
print(f"Total rows found: {len(rows)}")

for idx, row in enumerate(rows, 1):
    parsed = parser._parse_row(row)
    if parsed:
        title = parsed["title"]
        size_human = parsed["size_human"]
        size_bytes = parsed["size_bytes"]
        print(f"Row #{idx}: title='{title[:30]}', size_human='{size_human}', size_bytes={size_bytes}")
        if size_bytes == 1024 or size_human == "0 B":
            print(f"\n[!] Row #{idx} HAS 1 KiB SIZE!")
            print("Row HTML snippet:")
            print(str(row)[:800])
