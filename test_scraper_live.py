import asyncio
import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.scraper.browser import ExtToScraper


async def main():
    parser = argparse.ArgumentParser(description="Live scraper test for ext.to")
    parser.add_argument("--query", "-q", default="ubuntu", help="Search query")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--domain", default="https://extto.com", help="ext.to domain")
    args = parser.parse_args()

    print(f"[*] Initializing ExtToScraper (domain: {args.domain}, headless: {args.headless})...", flush=True)
    scraper = ExtToScraper(base_url=args.domain, headless=args.headless)

    print(f"[*] Searching for query: '{args.query}'...", flush=True)
    try:
        results = await scraper.search(args.query, max_magnets=5)
        print(f"[+] Found {len(results)} results!", flush=True)
        for idx, item in enumerate(results[:10], 1):
            print(f"\n--- Result #{idx} ---", flush=True)
            print(f"Title:    {item.title}", flush=True)
            print(f"Category: {item.category} (Torznab Cat ID: {item.torznab_cat_id})", flush=True)
            print(f"Size:     {item.size_human} ({item.size_bytes} bytes)", flush=True)
            print(f"Seed/Leech: {item.seeders} / {item.leechers}", flush=True)
            print(f"Infohash: {item.infohash}", flush=True)
            print(f"Details:  {item.details_url}", flush=True)
            if item.magnet_link:
                print(f"Magnet:   {item.magnet_link[:80]}...", flush=True)
    except Exception as e:
        print(f"[!] Scraping failed: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
