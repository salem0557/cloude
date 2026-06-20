#!/usr/bin/env python3
"""Crypto news + rumours collector.

Reads several well-known crypto news RSS feeds, normalises every article and
splits them into two buckets:

* ``news``   — straight reporting.
* ``rumors`` — speculative pieces about coins that *might* pump: presales,
  upcoming listings, airdrops, "could 100x" style headlines, etc.

The result is written to ``docs/crypto/data/news.json`` and served by GitHub
Pages. Prices for the coin boxes are fetched live in the browser, so this
script only deals with text.

No external feed library is required: feeds are parsed with the same
``requests`` + ``BeautifulSoup`` stack the job scraper already uses.
"""

import json
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DOCS = Path(__file__).resolve().parent.parent / "docs"
OUT = DOCS / "crypto" / "data" / "news.json"

# (source label, feed url). Sources skewed towards altcoin/speculation
# coverage so the "rumours" bucket actually fills up.
FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("Bitcoinist", "https://bitcoinist.com/feed/"),
    ("NewsBTC", "https://www.newsbtc.com/feed/"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("U.Today", "https://u.today/rss"),
    ("Crypto Briefing", "https://cryptobriefing.com/feed/"),
    ("BeInCrypto", "https://beincrypto.com/feed/"),
]

# Headlines containing any of these are treated as speculation / rumours.
RUMOR_PATTERNS = [
    r"rumou?r", r"speculat", r"could (?:soar|surge|explode|100x|10x|pump|rally)",
    r"\bmight\b", r"\bset to\b", r"\bpoised to\b", r"\bcould\b.*\b(?:moon|pump|surge|rally|explode)",
    r"pre-?sale", r"\bIDO\b", r"\bICO\b", r"\bIEO\b", r"airdrop",
    r"to list", r"listing", r"will list", r"launch", r"new token", r"new coin",
    r"\b\d{2,3}x\b", r"moonshot", r"\bpump\b", r"next big", r"hidden gem",
    r"to explode", r"price prediction", r"expected to", r"whisper", r"insider",
    r"low cap", r"micro-?cap", r"undervalued", r"presale", r"meme ?coin",
]
RUMOR_RE = re.compile("|".join(RUMOR_PATTERNS), re.IGNORECASE)

# Tags surfaced on rumour cards so the reader sees *why* it was flagged.
TAG_RULES = [
    ("Presale", r"pre-?sale|presale|\bIDO\b|\bICO\b|\bIEO\b"),
    ("Listing", r"to list|listing|will list"),
    ("Airdrop", r"airdrop"),
    ("Launch", r"launch|new token|new coin"),
    ("Meme", r"meme ?coin|dog(?:e|wif)|pepe|shib"),
    ("Big move", r"\d{2,3}x|moonshot|to explode|could (?:soar|surge|pump|rally)|pump"),
    ("Prediction", r"price prediction|expected to|poised to|set to"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

MAX_PER_FEED = 25
MAX_NEWS = 80
MAX_RUMORS = 60


def clean_text(html: str) -> str:
    """Strip tags/whitespace from an RSS summary and trim it."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:280]


def parse_date(raw: str) -> str:
    """Return an ISO-8601 UTC string, or '' if the date can't be read."""
    if not raw:
        return ""
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)  # RFC-822 (RSS)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO (Atom)
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def extract_link(node) -> str:
    """Pull the article URL out of an RSS <item> or Atom <entry>."""
    link = node.find("link")
    if link is not None:
        href = link.get("href")
        if href:
            return href.strip()
        if link.text and link.text.strip():
            return link.text.strip()
    guid = node.find("guid")
    if guid is not None and guid.text and guid.text.strip().startswith("http"):
        return guid.text.strip()
    return ""


def tags_for(text: str):
    return [name for name, pat in TAG_RULES if re.search(pat, text, re.IGNORECASE)]


def fetch_feed(label: str, url: str):
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! {label}: {exc}", file=sys.stderr)
        return items

    soup = BeautifulSoup(resp.content, "html.parser")
    nodes = soup.find_all("item") or soup.find_all("entry")
    for node in nodes[:MAX_PER_FEED]:
        title_el = node.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue
        url_ = extract_link(node)
        if not url_:
            continue
        date_el = node.find("pubdate") or node.find("published") or node.find("updated")
        published = parse_date(date_el.get_text(strip=True) if date_el else "")
        desc_el = node.find("description") or node.find("summary") or node.find("content")
        summary = clean_text(desc_el.decode_contents() if desc_el else "")
        items.append(
            {
                "title": title,
                "url": url_,
                "source": label,
                "published": published,
                "summary": summary,
            }
        )
    print(f"  - {label}: {len(items)} items")
    return items


def main():
    print("Collecting crypto news...")
    all_items, seen = [], set()
    for label, url in FEEDS:
        for it in fetch_feed(label, url):
            key = it["url"].split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            all_items.append(it)

    # Newest first; undated items sink to the bottom.
    all_items.sort(key=lambda x: x["published"] or "", reverse=True)

    news, rumors = [], []
    for it in all_items:
        haystack = f"{it['title']} {it['summary']}"
        if RUMOR_RE.search(haystack):
            rumor = dict(it)
            rumor["tags"] = tags_for(haystack) or ["Speculation"]
            rumors.append(rumor)
        else:
            news.append(it)

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "news": news[:MAX_NEWS],
        "rumors": rumors[:MAX_RUMORS],
        "sources": [label for label, _ in FEEDS],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(payload['news'])} news + {len(payload['rumors'])} rumours -> {OUT}")


if __name__ == "__main__":
    main()
