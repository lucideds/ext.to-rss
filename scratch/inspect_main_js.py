import re
from curl_cffi import requests

r = requests.get("https://extto.com/static/js/main.min.js", impersonate="chrome120")
js = r.text

pos = js.find("computeHMAC")
if pos != -1:
    print("=== computeHMAC function ===")
    print(js[pos-50:pos+500])
