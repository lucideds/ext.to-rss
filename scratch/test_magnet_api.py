import re
import time
import hashlib
from bs4 import BeautifulSoup
from curl_cffi import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

# 1. Fetch detail page HTML
url = "https://extto.com/ubuntu-the-complete-guide-11th-edition-2021-pdf-8696336/"
s = requests.Session(impersonate="chrome120")
r = s.get(url, headers=headers)
html = r.text

soup = BeautifulSoup(html, "lxml")

# 2. Extract csrfToken from meta tag
csrf_meta = soup.find("meta", attrs={"name": "csrf-token"})
csrf_token = csrf_meta["content"] if csrf_meta else ""

# 3. Extract pageToken from script tag or window variable
page_token = ""
match = re.search(r"window\.pageToken\s*=\s*[\"']([^\"']+)[\"']", html)
if match:
    page_token = match.group(1)

print(f"[+] CSRF Token: {csrf_token}")
print(f"[+] Page Token: {page_token}")

# 4. Compute SHA256 HMAC
torrent_id = 8696336
timestamp = int(time.time())
raw_data = f"{torrent_id}|{timestamp}|{page_token}"
hmac_hash = hashlib.sha256(raw_data.encode("utf-8")).hexdigest()

print(f"[+] Raw data: {raw_data}")
print(f"[+] Computed HMAC: {hmac_hash}")

# 5. Call /ajax/getTorrentMagnet.php API
post_data = {
    "torrent_id": torrent_id,
    "download_type": "magnet",
    "timestamp": timestamp,
    "hmac": hmac_hash,
    "sessid": csrf_token,
}

api_url = "https://extto.com/ajax/getTorrentMagnet.php"
api_resp = s.post(api_url, data=post_data, headers={**headers, "Referer": url})

print("\n=== API RESPONSE ===")
print("Status:", api_resp.status_code)
print("Response JSON:", api_resp.text)
