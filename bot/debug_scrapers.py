"""
Debug script — fetches one page from each site via ScraperAPI and reports
the HTML structure so we can write correct CSS selectors.

Usage:
    python -m bot.debug_scrapers
"""
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    from curl_cffi import requests
except ImportError:
    import requests

SCRAPER_KEY = os.getenv("SCRAPER_API_KEY", "")

PAGES = {
    "Amazon.sa":  "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031&s=price-desc-rank",
    "Noon":       "https://www.noon.com/saudi-en/electronics/?sort_by=discount&limit=30",
    "Jarir":      "https://www.jarir.com/sa-en/computers-and-electronics",
    "Extra":      "https://www.extra.com/en-sa/mobile-tablets/smartphones",
    "SharafDG":   "https://www.sharafdg.com/sa/en/mobile-phones-tablets/smartphones",
}

# CSS patterns to probe for on each page
PROBES = [
    # generic product containers
    ('[data-component-type="s-search-result"]', "Amazon product card"),
    ('.product-item',        "Magento product item"),
    ('.productContainer',    "Noon product container"),
    ('[data-qa="product-card"]', "Noon QA product card"),
    ('article[class*="product"]', "generic product article"),
    ('.product-tile',        "product tile"),
    ('[class*="ProductCard"]', "React ProductCard"),
    ('[class*="product-card"]', "product-card class"),
    # price elements
    ('span.a-price',         "Amazon price"),
    ('[class*="price"]',     "price element"),
    ('.special-price',       "sale price (Magento)"),
    # discount badges
    ('[class*="discount"]',  "discount badge"),
    ('.savingsPercentage',   "savings %"),
    # JSON data
    ('script[type="application/ld+json"]', "JSON-LD schema"),
    ('script#__NEXT_DATA__', "Next.js data"),
    ('#__NEXT_DATA__',       "Next.js data alt"),
]


def fetch(url):
    if SCRAPER_KEY:
        resp = requests.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_KEY, "url": url, "country_code": "sa"},
            timeout=60,
        )
    else:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"
        })
    return resp


def analyse(name, url):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  {url}")
    print(f"{'='*60}")
    try:
        resp = fetch(url)
        print(f"  HTTP {resp.status_code}  |  {len(resp.text):,} bytes")
        if resp.status_code != 200:
            return

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")

        print(f"  <title>: {soup.title.string.strip() if soup.title else 'n/a'}")

        # Detect framework
        if soup.find("script", id="__NEXT_DATA__"):
            print("  Framework: Next.js (JSON in __NEXT_DATA__)")
        elif soup.find(attrs={"data-reactroot": True}) or "react" in resp.text[:5000].lower():
            print("  Framework: React SPA")
        elif "Magento" in resp.text[:5000] or "mage/" in resp.text:
            print("  Framework: Magento")
        else:
            print("  Framework: unknown / SSR")

        # Probe selectors
        print("\n  Selector hits:")
        for sel, label in PROBES:
            found = soup.select(sel)
            if found:
                sample = found[0].get_text(strip=True)[:80].replace("\n", " ")
                print(f"  ✅ {len(found):3d}x  [{label}]  «{sample}»")

        # Check for JSON-LD product data
        ld = soup.find("script", type="application/ld+json")
        if ld:
            text = ld.string or ""
            if "Product" in text or "offer" in text.lower():
                print(f"\n  JSON-LD contains product/offer data ({len(text)} chars)")

        # Check for Next.js embedded data
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data:
            text = next_data.string or ""
            if "price" in text.lower() and ("product" in text.lower() or "item" in text.lower()):
                # Count product-like objects
                hits = len(re.findall(r'"price"', text))
                print(f"\n  __NEXT_DATA__ contains {hits} 'price' references ({len(text):,} chars)")

    except Exception as exc:
        print(f"  ERROR: {exc}")


if __name__ == "__main__":
    if not SCRAPER_KEY:
        print("⚠️  SCRAPER_API_KEY not set — requests may be blocked by 403")
    for name, url in PAGES.items():
        analyse(name, url)
    print("\nDone.")
