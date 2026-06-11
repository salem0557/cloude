#!/usr/bin/env python3
"""Riyadh LinkedIn post finder.

Finds public LinkedIn posts about the configured keywords whose text (or
author, when available) points at Riyadh / Saudi Arabia, so they can be
replied to from the website at docs/posts/.

Free mode (default): asks Bing and DuckDuckGo for LinkedIn posts indexed
by them (``site:linkedin.com/posts <keyword> Riyadh``). Search engines
only index a fraction of LinkedIn and may block automation, so this is a
best-effort feed; the website also has one-click live LinkedIn search
links which always show the freshest posts.

Paid mode (optional): when an APIFY_TOKEN repository secret is set, an
Apify actor (default ``harvestapi~linkedin-post-search``) is also run.
It searches LinkedIn itself and returns fresh posts with author profile
data; posts whose author location is known and outside Saudi Arabia are
dropped. Override the actor with an APIFY_ACTOR repository variable, or
the entire actor input with an APIFY_INPUT variable (JSON).

Posts are never deleted: newly discovered posts get today's date as
``first_seen`` so the website can flag them as NEW.
"""

import base64
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

DOCS = Path(__file__).resolve().parent.parent / "docs"
DATA_FILE = DOCS / "posts" / "data" / "posts.json"

KEYWORDS = [
    "IT Management",
    "IT Project Manager",
    "Data Acquisition",
    "Data Sharing",
    "Digital Transformation",
    "HR",
    "Saudi",
]

# Free mode has no access to author profiles, so the post text standing in
# for the author's location is the only available signal.
LOCATION_TERMS = ["Riyadh", "Saudi Arabia"]
LOCATION_RE = re.compile(r"riyadh|saudi|الرياض|السعودية", re.IGNORECASE)

MAX_PER_QUERY = 30
REQUEST_TIMEOUT = 25

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def matches_keyword(text, keyword):
    """True when the text shares at least one word with the keyword."""
    tokens = re.findall(r"[A-Za-z]+", keyword)
    return any(
        re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE)
        for t in tokens
        if len(t) >= 2
    )


def fetch(url, *, params=None, timeout=REQUEST_TIMEOUT):
    resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


# --------------------------------------------------------------------------
# LinkedIn URL helpers
# --------------------------------------------------------------------------

POST_PATH_RE = re.compile(r"^/(posts|pulse|feed/update)/", re.IGNORECASE)


def canonical_post_url(url):
    """Normalize a LinkedIn post URL so the same post always dedupes.

    Returns None for URLs that are not individual LinkedIn posts/articles.
    """
    parts = urlsplit(url)
    if not parts.netloc.lower().endswith("linkedin.com"):
        return None
    path = parts.path.rstrip("/")
    if not POST_PATH_RE.match(path + "/"):
        return None
    return urlunsplit(("https", "www.linkedin.com", path, "", ""))


def author_from_url(url):
    """LinkedIn post URLs look like /posts/{profile-slug}_{title}-activity-{id}."""
    match = re.search(r"linkedin\.com/posts/([^/_?#]+)_", url)
    if not match:
        return ""
    # Drop trailing id-like tokens ("ahmed-ali-94b21a3" -> "ahmed ali").
    words = [
        w for w in match.group(1).split("-")
        if not re.fullmatch(r"[0-9]+|[0-9a-f]{5,}", w)
    ]
    return " ".join(w.capitalize() for w in words) or match.group(1)


def strip_result_title(title):
    return clean_text(re.sub(r"\s*[|\-–]\s*LinkedIn\s*$", "", title or ""))


# --------------------------------------------------------------------------
# Free sources: Bing RSS and DuckDuckGo HTML
# --------------------------------------------------------------------------

def unwrap_bing(url):
    """Bing sometimes wraps links as bing.com/ck/a?...&u=a1<base64url>."""
    if "bing.com/ck/" not in url:
        return url
    wrapped = parse_qs(urlsplit(url).query).get("u", [""])[0]
    if wrapped.startswith("a1"):
        wrapped = wrapped[2:]
        try:
            padded = wrapped + "=" * (-len(wrapped) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        except Exception:
            pass
    return url


def search_bing(query):
    resp = fetch(
        "https://www.bing.com/search",
        params={"q": query, "format": "rss", "count": MAX_PER_QUERY},
    )
    results = []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        print(f"  Bing: RSS parse error: {exc}", file=sys.stderr)
        return results
    for item in root.iter("item"):
        results.append({
            "title": strip_result_title(item.findtext("title")),
            "snippet": clean_text(item.findtext("description")),
            "url": unwrap_bing(clean_text(item.findtext("link"))),
        })
    return results


def unwrap_ddg(url):
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    if "duckduckgo.com" in parts.netloc and parts.path.startswith("/l/"):
        return unquote(parse_qs(parts.query).get("uddg", [""])[0]) or url
    return url


def search_duckduckgo(query):
    resp = fetch("https://html.duckduckgo.com/html/", params={"q": query})
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for block in soup.select(".result"):
        link = block.select_one("a.result__a[href]")
        if not link:
            continue
        snippet = block.select_one(".result__snippet")
        results.append({
            "title": strip_result_title(link.get_text()),
            "snippet": clean_text(snippet.get_text()) if snippet else "",
            "url": unwrap_ddg(link["href"]),
        })
    if not results and "detected an anomaly" in resp.text.lower():
        print("  DuckDuckGo: blocked (anomaly page)", file=sys.stderr)
    return results


ENGINES = {
    "Bing": search_bing,
    "DuckDuckGo": search_duckduckgo,
}


def free_search(keyword):
    """Posts for one keyword from all search engines that are not blocked."""
    posts = []
    for location in LOCATION_TERMS:
        if keyword == "Saudi" and location == "Saudi Arabia":
            continue  # redundant query
        query = f'site:linkedin.com/posts "{keyword}" {location}'
        for engine, searcher in list(ENGINES.items()):
            try:
                results = searcher(query)
            except requests.RequestException as exc:
                print(f"  {engine}: {exc} — skipping engine this run", file=sys.stderr)
                ENGINES.pop(engine, None)
                continue
            kept = 0
            for r in results:
                url = canonical_post_url(r["url"])
                text = f'{r["title"]} {r["snippet"]}'
                if not url:
                    continue
                if not matches_keyword(text, keyword):
                    continue
                if not LOCATION_RE.search(text + " " + url):
                    continue
                kept += 1
                posts.append({
                    "title": r["title"] or url,
                    "snippet": r["snippet"],
                    "author": author_from_url(url),
                    "author_location": None,
                    "url": url,
                    "posted": None,
                    "source": engine,
                })
            print(f'{engine:<11} "{keyword}" + {location}: '
                  f"{len(results)} results, {kept} LinkedIn posts kept")
    return posts


# --------------------------------------------------------------------------
# Paid source: Apify actor (only used when APIFY_TOKEN is configured)
# --------------------------------------------------------------------------

def pick(item, *paths):
    """First non-empty value at any of the dotted paths."""
    for path in paths:
        value = item
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value:
            return value
    return None


def search_apify():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return []
    actor = os.environ.get("APIFY_ACTOR") or "harvestapi~linkedin-post-search"
    raw_input = os.environ.get("APIFY_INPUT")
    if raw_input:
        payload = json.loads(raw_input)
    else:
        payload = {
            "searchQueries": [f"{kw} Riyadh" for kw in KEYWORDS],
            "maxPosts": 20,
            "postedLimit": "24h",
        }
    resp = requests.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        params={"token": token, "timeout": 280, "format": "json"},
        json=payload,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"WARN Apify actor {actor} failed ({resp.status_code}): "
              f"{resp.text[:300]}", file=sys.stderr)
        return []
    posts = []
    for item in resp.json():
        if not isinstance(item, dict):
            continue
        url = pick(item, "url", "postUrl", "linkedinUrl", "link", "shareUrl")
        text = clean_text(pick(item, "text", "content", "postText",
                                "commentary", "description", "title") or "")
        if not url:
            continue
        url = canonical_post_url(url) or url
        location = clean_text(pick(item, "authorLocation", "author.location",
                                   "author.geoLocationName",
                                   "authorProfile.location") or "")
        # Author location is the real filter; drop clearly non-Saudi authors.
        if location and not LOCATION_RE.search(location):
            continue
        posted = str(pick(item, "postedAt", "date", "publishedAt",
                          "postedDate", "time") or "")[:10] or None
        posts.append({
            "title": text[:140] or url,
            "snippet": text[:400],
            "author": clean_text(pick(item, "authorName", "author.name",
                                      "author.fullName", "authorFullName",
                                      "author.title") or "")
                      or author_from_url(url),
            "author_location": location or None,
            "url": url,
            "posted": posted,
            "source": "Apify",
        })
    print(f"Apify       all keywords: {len(posts)} posts kept")
    return posts


# --------------------------------------------------------------------------
# Merge + persist
# --------------------------------------------------------------------------

def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"updated": None, "posts": []}


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = load_existing()
    by_url = {post["url"]: post for post in existing["posts"]}

    found = []
    for keyword in KEYWORDS:
        for post in free_search(keyword):
            post["keywords"] = [keyword]
            found.append(post)
    for post in search_apify():
        post["keywords"] = [kw for kw in KEYWORDS
                            if matches_keyword(post["snippet"], kw)] or ["Saudi"]
        found.append(post)

    new_count = 0
    for post in found:
        seen = by_url.get(post["url"])
        if seen:
            for kw in post["keywords"]:
                if kw not in seen["keywords"]:
                    seen["keywords"].append(kw)
            for field in ("posted", "author_location", "snippet", "author"):
                if post.get(field) and not seen.get(field):
                    seen[field] = post[field]
        else:
            post["first_seen"] = today
            by_url[post["url"]] = post
            new_count += 1

    posts = sorted(
        by_url.values(),
        key=lambda p: (p["first_seen"], p.get("posted") or ""),
        reverse=True,
    )
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "posts": posts},
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\n{len(posts)} posts stored ({new_count} new this run)")


if __name__ == "__main__":
    main()
