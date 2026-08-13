import urllib.request
import xml.etree.ElementTree as ET

url = "http://127.0.0.1:8000/api?t=search&q=last+of+us+S01E02"
xml_data = urllib.request.urlopen(url).read()
root = ET.fromstring(xml_data)

ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
sizes = [attr.attrib["value"] for attr in root.findall(".//torznab:attr[@name='size']", namespaces=ns)]

print(f"Parsed sizes count: {len(sizes)}")
print("Count of 1024 byte (1 KiB) sizes:", sizes.count("1024"))
print("\nSample parsed sizes from live API:")
for s in sizes[:10]:
    val_bytes = int(s)
    val_mb = val_bytes / (1024 * 1024)
    val_gb = val_bytes / (1024 * 1024 * 1024)
    if val_gb >= 1.0:
        print(f"  - {val_gb:.2f} GB ({val_bytes} bytes)")
    else:
        print(f"  - {val_mb:.1f} MB ({val_bytes} bytes)")
