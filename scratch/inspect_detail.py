import re
from bs4 import BeautifulSoup
from curl_cffi import requests

# Fetch detail page
url = "https://extto.com/ubuntu-the-complete-guide-11th-edition-2021-pdf-8696336/"
r = requests.get(url, impersonate="chrome120")
html = r.text

soup = BeautifulSoup(html, "lxml")

print("=== SCRIPT TAGS ===")
for s in soup.find_all("script"):
    src = s.get("src")
    if src:
        print("Script src:", src)

print("\n=== MAGNET / DOWNLOAD BUTTONS ===")
for elem in soup.find_all(attrs={"data-id": True}):
    print(elem.name, elem.get("class"), "data-id:", elem.get("data-id"), "href:", elem.get("href"))

# Look for inline JS containing magnet or hash or post or ajax
print("\n=== MATCHES FOR MAGNET / DOWNLOAD / AJAX IN INLINE JS ===")
for s in soup.find_all("script"):
    if not s.get("src") and s.string:
        matches = re.findall(r"/[a-zA-Z0-9_\-/]+", s.string)
        for m in matches:
            if any(x in m.lower() for x in ["magnet", "download", "post", "ajax", "get", "torrent"]):
                print("Found endpoint in JS:", m)
