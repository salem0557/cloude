#!/usr/bin/env python3
"""Daily Riyadh job search.

Searches LinkedIn, Bayt.com and Naukrigulf for a fixed set of keywords in
Riyadh, Saudi Arabia, merges the results with previously found jobs and
writes everything to docs/data/jobs.json (served by GitHub Pages).

Jobs are never deleted: newly discovered jobs get today's date as
``first_seen`` so the website can flag them as NEW.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

KEYWORDS = [
    "IT Management",
    "IT Project Manager",
    "Data Acquisition & Sharing Lead",
    "Digital Transformation",
]

CITY = "Riyadh"
DATA_FILE = Path(__file__).resolve().parent.parent / "docs" / "data" / "jobs.json"
MAX_PER_SOURCE_KEYWORD = 40
REQUEST_TIMEOUT = 30

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class SourceBlocked(Exception):
    """The site is refusing automated requests; skip its remaining keywords."""


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_url(url):
    """Strip query string / fragment so the same job always dedupes."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch(url, *, params=None, headers=None, as_json=False, timeout=REQUEST_TIMEOUT):
    merged = dict(BROWSER_HEADERS)
    if headers:
        merged.update(headers)
    resp = requests.get(url, params=params, headers=merged, timeout=timeout)
    resp.raise_for_status()
    return resp.json() if as_json else resp.text


# --------------------------------------------------------------------------
# LinkedIn (public guest job feed, no login required)
# --------------------------------------------------------------------------

def search_linkedin(keyword):
    jobs = []
    for start in (0, 25):
        html = fetch(
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
            params={
                "keywords": keyword,
                "location": "Riyadh, Saudi Arabia",
                "start": start,
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.base-card, li > div.base-search-card")
        if not cards:
            break
        for card in cards:
            link = card.select_one("a.base-card__full-link[href]")
            title = card.select_one(".base-search-card__title")
            if not link or not title:
                continue
            company = card.select_one(".base-search-card__subtitle")
            location = card.select_one(".job-search-card__location")
            posted = card.select_one("time[datetime]")
            jobs.append({
                "title": clean_text(title.get_text()),
                "company": clean_text(company.get_text()) if company else "",
                "location": clean_text(location.get_text()) if location else CITY,
                "url": canonical_url(link["href"]),
                "posted": posted["datetime"] if posted else None,
                "source": "LinkedIn",
            })
        if len(cards) < 25:
            break
    return jobs


# --------------------------------------------------------------------------
# Bayt.com
# --------------------------------------------------------------------------

def search_bayt(keyword):
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    urls = [
        f"https://www.bayt.com/en/saudi-arabia/jobs/{slug}-jobs-in-riyadh/",
        f"https://www.bayt.com/en/saudi-arabia/jobs/?text={quote(keyword)}&loc={quote(CITY)}",
    ]
    errors = []
    for url in urls:
        try:
            html = fetch(url)
        except requests.RequestException as exc:
            errors.append(exc)
            continue
        jobs = parse_bayt_page(html)
        if jobs:
            return jobs
        print(f"  bayt: {url} -> 200 but 0 jobs parsed ({len(html)} bytes)", file=sys.stderr)
    if len(errors) == len(urls):
        raise SourceBlocked(f"Bayt refused all requests: {errors[-1]}")
    return []


def parse_bayt_page(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    # Strategy 1: schema.org JSON-LD blocks embedded in the page.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in extract_job_postings(data):
            url = posting.get("url") or posting.get("sameAs")
            title = posting.get("title") or posting.get("name")
            if not url or not title:
                continue
            org = posting.get("hiringOrganization") or {}
            jobs.append({
                "title": clean_text(title),
                "company": clean_text(org.get("name", "") if isinstance(org, dict) else str(org)),
                "location": CITY,
                "url": canonical_url(url),
                "posted": (posting.get("datePosted") or "")[:10] or None,
                "source": "Bayt",
            })
    if jobs:
        return jobs

    # Strategy 2: job list markup.
    for li in soup.select("li[data-js-job]"):
        link = li.select_one("h2 a[href], a[data-js-aid='jobID']")
        if not link or not link.get("href"):
            continue
        company = li.select_one(".jb-company, b.jb-company, [class*='company']")
        jobs.append({
            "title": clean_text(link.get_text()),
            "company": clean_text(company.get_text()) if company else "",
            "location": CITY,
            "url": canonical_url(requests.compat.urljoin("https://www.bayt.com", link["href"])),
            "posted": None,
            "source": "Bayt",
        })
    return jobs


def extract_job_postings(data):
    """Recursively yield JobPosting dicts from arbitrary JSON-LD."""
    if isinstance(data, dict):
        if data.get("@type") == "JobPosting":
            yield data
        for value in data.values():
            yield from extract_job_postings(value)
    elif isinstance(data, list):
        for item in data:
            yield from extract_job_postings(item)


# --------------------------------------------------------------------------
# Naukrigulf
# --------------------------------------------------------------------------

def search_naukrigulf(keyword):
    try:
        data = fetch(
            "https://www.naukrigulf.com/spapi/jobapi/search",
            params={
                "Experience": "",
                "Keywords": keyword,
                "KeywordsAr": "",
                "Limit": str(MAX_PER_SOURCE_KEYWORD),
                "Location": CITY.lower(),
                "LocationAr": "",
                "Offset": "0",
                "SortPreference": "",
                "breadcrumb": "1",
                "locationId": "",
                "nationality": "",
                "nationalityLabel": "",
                "pageNo": "1",
                "srchId": "",
            },
            headers={
                "appid": "205",
                "systemid": "2323",
                "Accept": "application/json",
            },
            as_json=True,
            timeout=15,
        )
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"  naukrigulf api: {exc}; falling back to HTML", file=sys.stderr)
        return search_naukrigulf_html(keyword)

    jobs = []
    for item in data.get("jobs", []):
        url = item.get("jdURL") or ""
        title = item.get("designation") or item.get("title")
        if not url or not title:
            continue
        if not url.startswith("http"):
            url = "https://www.naukrigulf.com/" + url.lstrip("/")
        location = item.get("location") or CITY
        jobs.append({
            "title": clean_text(title),
            "company": clean_text(item.get("companyName", "")),
            "location": clean_text(location),
            "url": canonical_url(url),
            "posted": (item.get("latestPostedDate") or "")[:10] or None,
            "source": "Naukrigulf",
        })
    return jobs


def search_naukrigulf_html(keyword):
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    try:
        html = fetch(f"https://www.naukrigulf.com/{slug}-jobs-in-riyadh", timeout=15)
    except requests.Timeout as exc:
        raise SourceBlocked(f"Naukrigulf timing out (connection stalled): {exc}")
    except requests.RequestException as exc:
        print(f"  naukrigulf html: {exc}", file=sys.stderr)
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in extract_job_postings(data):
            url = posting.get("url")
            title = posting.get("title") or posting.get("name")
            if not url or not title:
                continue
            org = posting.get("hiringOrganization") or {}
            jobs.append({
                "title": clean_text(title),
                "company": clean_text(org.get("name", "") if isinstance(org, dict) else str(org)),
                "location": CITY,
                "url": canonical_url(url),
                "posted": (posting.get("datePosted") or "")[:10] or None,
                "source": "Naukrigulf",
            })
    return jobs


# --------------------------------------------------------------------------
# Merge + persist
# --------------------------------------------------------------------------

SOURCES = {
    "LinkedIn": search_linkedin,
    "Bayt": search_bayt,
    "Naukrigulf": search_naukrigulf,
}


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"updated": None, "jobs": []}


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = load_existing()
    by_url = {job["url"]: job for job in existing["jobs"]}

    new_count = 0
    for source, searcher in SOURCES.items():
        for keyword in KEYWORDS:
            try:
                results = searcher(keyword)[:MAX_PER_SOURCE_KEYWORD]
            except SourceBlocked as exc:
                print(f"WARN {source} is blocking automation, skipping it today: {exc}",
                      file=sys.stderr)
                break
            except Exception as exc:  # one failing source must not kill the run
                print(f"WARN {source} / '{keyword}': {exc}", file=sys.stderr)
                continue
            print(f"{source:<11} '{keyword}': {len(results)} jobs")
            for job in results:
                seen = by_url.get(job["url"])
                if seen:
                    if keyword not in seen["keywords"]:
                        seen["keywords"].append(keyword)
                    if job.get("posted") and not seen.get("posted"):
                        seen["posted"] = job["posted"]
                else:
                    job["keywords"] = [keyword]
                    job["first_seen"] = today
                    by_url[job["url"]] = job
                    new_count += 1

    jobs = sorted(
        by_url.values(),
        key=lambda j: (j["first_seen"], j.get("posted") or ""),
        reverse=True,
    )
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs},
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nTotal jobs stored: {len(jobs)} ({new_count} new today)")


if __name__ == "__main__":
    main()
