#!/usr/bin/env python3
"""Daily Riyadh job search.

Searches LinkedIn, GulfTalent, Akhtaboot, Tanqeeb (and Jooble when an API
key is configured) for each profile's keywords in Riyadh, Saudi Arabia,
merges the results with previously found jobs and writes them to that
profile's jobs.json (served by GitHub Pages).

Jobs are never deleted: newly discovered jobs get today's date as
``first_seen`` so the website can flag them as NEW.

Google Jobs is not included: Google offers no free programmatic access and
blocks automated queries, so the website links to it for manual searching.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

DOCS = Path(__file__).resolve().parent.parent / "docs"

PROFILES = {
    "Salem": {
        "keywords": [
            "IT Management",
            "IT Project Manager",
            "Digital Transformation",
            "Data Management",
            "Program Manager",
            "Data Acquisition",
            "Data Sharing",
        ],
        "cities": ["Riyadh"],
        "data_file": DOCS / "data" / "jobs.json",
    },
    "Othman": {
        "keywords": [
            "IT Support",
            "Help Desk",
            "Technical Support",
            "IT Specialist",
            "System Administrator",
            "IT Fresh Graduate",
        ],
        "cities": ["Riyadh"],
        "data_file": DOCS / "othman" / "data" / "jobs.json",
    },
    "Omer": {
        "keywords": [
            "Supply Chain",
            "Procurement",
            "Logistics",
            "Operations Manager",
            "Mechanical Engineer",
            "Maintenance Engineer",
            "Facilities Management",
        ],
        "cities": ["Riyadh", "Hail"],
        "data_file": DOCS / "omer" / "data" / "jobs.json",
    },
}

MAX_PER_SOURCE_KEYWORD = 40
REQUEST_TIMEOUT = 25

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class SourceBlocked(Exception):
    """The site is refusing automated requests; skip its remaining keywords."""


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def matches_keyword(title, keyword):
    """True when the job title shares at least one word with the keyword."""
    tokens = re.findall(r"[A-Za-z]+", keyword)
    return any(
        re.search(rf"\b{re.escape(t)}\b", title, re.IGNORECASE)
        for t in tokens
        if len(t) >= 2
    )


def slugify(keyword):
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")


def canonical_url(url):
    """Strip query string / fragment so the same job always dedupes."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch(url, *, params=None, headers=None, timeout=REQUEST_TIMEOUT):
    merged = dict(BROWSER_HEADERS)
    if headers:
        merged.update(headers)
    resp = requests.get(url, params=params, headers=merged, timeout=timeout)
    resp.raise_for_status()
    return resp


def debug_dump(source, resp, parsed_count):
    """When a page yields nothing, log enough detail to fix the parser."""
    soup = BeautifulSoup(resp.text, "html.parser")
    title = clean_text(soup.title.get_text()) if soup.title else "(no title)"
    links = [a.get("href", "") for a in soup.find_all("a", href=True)]
    joblinks = [h for h in links if "job" in h.lower()][:5]
    print(
        f"  {source}: {resp.url} -> {resp.status_code}, {len(resp.text)} bytes, "
        f"{parsed_count} jobs parsed; title={title!r}; "
        f"{len(links)} links, samples={joblinks}",
        file=sys.stderr,
    )
    # Raw probe: listings may live in embedded JSON rather than <a> tags.
    matches = re.finditer(
        r".{60}(?:jobid|job_id|jobtitle|job-title|\"jobs\"|/job/|wzyfa).{60}",
        resp.text,
        re.IGNORECASE,
    )
    for n, match in enumerate(matches):
        if n >= 5:
            break
        print(f"    raw: ...{clean_text(match.group(0))}...", file=sys.stderr)


# --------------------------------------------------------------------------
# schema.org JSON-LD helpers (most job boards embed JobPosting data)
# --------------------------------------------------------------------------

def extract_job_postings(data):
    """Recursively yield JobPosting dicts from arbitrary JSON-LD."""
    if isinstance(data, dict):
        type_ = data.get("@type")
        if type_ == "JobPosting" or (isinstance(type_, list) and "JobPosting" in type_):
            yield data
        for value in data.values():
            yield from extract_job_postings(value)
    elif isinstance(data, list):
        for item in data:
            yield from extract_job_postings(item)


def posting_location(posting):
    loc = posting.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion")]
            joined = ", ".join(p for p in parts if p)
            if joined:
                return joined
            country = addr.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name")
            return country or ""
        if isinstance(addr, str):
            return addr
    return ""


def parse_jsonld_jobs(html, base_url, source, city):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
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
            location = clean_text(posting_location(posting))
            # Keep jobs in the searched city; keep unknown locations too
            # (the page is already filtered to a city/Saudi search).
            if location and city.lower() not in location.lower():
                continue
            org = posting.get("hiringOrganization") or {}
            company = org.get("name", "") if isinstance(org, dict) else str(org)
            jobs.append({
                "title": clean_text(title),
                "company": clean_text(company),
                "location": location or city,
                "url": canonical_url(urljoin(base_url, url)),
                "posted": (posting.get("datePosted") or "")[:10] or None,
                "source": source,
            })
    return jobs


def try_urls(source, keyword, city, urls, extra_parser=None):
    """Fetch candidate URLs until one yields jobs relevant to the keyword.

    Raises SourceBlocked when every URL fails at the network level, so the
    caller can skip the source's remaining keywords for this run.
    """
    errors = []
    for url in urls:
        try:
            resp = fetch(url)
        except requests.Timeout as exc:
            errors.append(exc)
            print(f"  {source}: {url} -> timeout", file=sys.stderr)
            continue
        except requests.RequestException as exc:
            errors.append(exc)
            print(f"  {source}: {url} -> {exc}", file=sys.stderr)
            continue
        jobs = parse_jsonld_jobs(resp.text, resp.url, source, city)
        if not jobs and extra_parser:
            jobs = extra_parser(resp, keyword, city)
        # Sites sometimes ignore unknown search parameters and return their
        # newest jobs instead, so keep only titles related to the keyword.
        jobs = [j for j in jobs if matches_keyword(j["title"], keyword)]
        if jobs:
            return jobs
        debug_dump(source, resp, 0)
    if errors and len(errors) == len(urls):
        raise SourceBlocked(f"{source} refused all requests: {errors[-1]}")
    return []


# --------------------------------------------------------------------------
# LinkedIn (public guest job feed, no login required)
# --------------------------------------------------------------------------

def search_linkedin(keyword, city):
    jobs = []
    for start in (0, 25):
        resp = fetch(
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
            params={
                "keywords": keyword,
                "location": f"{city}, Saudi Arabia",
                "start": start,
            },
        )
        soup = BeautifulSoup(resp.text, "html.parser")
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
                "location": clean_text(location.get_text()) if location else city,
                "url": canonical_url(link["href"]),
                "posted": posted["datetime"] if posted else None,
                "source": "LinkedIn",
            })
        if len(cards) < 25:
            break
    return jobs


# --------------------------------------------------------------------------
# GulfTalent
# --------------------------------------------------------------------------

def parse_gulftalent_rows(resp, keyword, city):
    """GulfTalent lists jobs in table rows: title link, company, location."""
    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []
    for row in soup.find_all("tr"):
        link = row.select_one("a[href*='/jobs/']")
        if not link or not clean_text(link.get_text()):
            continue
        cells = [clean_text(td.get_text()) for td in row.find_all("td")]
        row_text = " ".join(cells).lower()
        if city.lower() not in row_text:
            continue
        company = cells[1] if len(cells) > 1 else ""
        jobs.append({
            "title": clean_text(link.get_text()),
            "company": company,
            "location": city,
            "url": canonical_url(urljoin(resp.url, link["href"])),
            "posted": None,
            "source": "GulfTalent",
        })
    return jobs


def search_gulftalent(keyword, city):
    slug = slugify(keyword)
    return try_urls(
        "GulfTalent",
        keyword,
        city,
        [
            f"https://www.gulftalent.com/saudi-arabia/jobs/title/{slug}",
            f"https://www.gulftalent.com/jobs/search?keywords={quote(keyword)}&country=saudi-arabia",
        ],
        extra_parser=parse_gulftalent_rows,
    )


# --------------------------------------------------------------------------
# Akhtaboot
# --------------------------------------------------------------------------

def parse_akhtaboot_links(resp, keyword, city):
    """Real Akhtaboot listings look like /en/saudi-arabia/jobs/riyadh/166912-Title."""
    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []
    seen = set()
    for link in soup.select("a[href*='/jobs/']"):
        title = clean_text(link.get_text())
        href = link.get("href", "")
        if not title or len(title) < 4 or href in seen:
            continue
        if not re.search(r"/jobs/.*\d{4,}", href) or city.lower() not in href.lower():
            continue
        seen.add(href)
        jobs.append({
            "title": title,
            "company": "",
            "location": city,
            "url": canonical_url(urljoin(resp.url, href)),
            "posted": None,
            "source": "Akhtaboot",
        })
    return jobs


def search_akhtaboot(keyword, city):
    return try_urls(
        "Akhtaboot",
        keyword,
        city,
        [
            f"https://www.akhtaboot.com/en/jobs/search?q={quote(keyword)}&country=Saudi+Arabia",
            f"https://www.akhtaboot.com/en/jobs/search?keywords={quote(keyword)}&country=Saudi+Arabia&city={quote(city)}",
        ],
        extra_parser=parse_akhtaboot_links,
    )


# --------------------------------------------------------------------------
# Tanqeeb (Middle East job search engine)
# --------------------------------------------------------------------------

def parse_tanqeeb_links(resp, keyword, city):
    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []
    seen = set()
    for link in soup.select("a[href*='/jobs/'], a[href*='/job/'], h2 a, h3 a"):
        title = clean_text(link.get_text())
        href = link.get("href", "")
        if not title or len(title) < 4 or not href or href in seen:
            continue
        if "tanqeeb" not in urljoin(resp.url, href):
            continue
        seen.add(href)
        jobs.append({
            "title": title,
            "company": "",
            "location": city,
            "url": canonical_url(urljoin(resp.url, href)),
            "posted": None,
            "source": "Tanqeeb",
        })
    return jobs


def search_tanqeeb(keyword, city):
    slug = slugify(keyword)
    cityslug = city.lower()
    return try_urls(
        "Tanqeeb",
        keyword,
        city,
        [
            f"https://saudi.tanqeeb.com/en/jobs/search?keywords={quote(keyword)}&state={cityslug}",
            f"https://www.tanqeeb.com/en/saudi-arabia/{slug}-jobs-in-{cityslug}",
            f"https://www.tanqeeb.com/en/jobs/search?keywords={quote(keyword)}&country=saudi-arabia",
        ],
        extra_parser=parse_tanqeeb_links,
    )


# --------------------------------------------------------------------------
# Jooble (job aggregator; official free API at jooble.org/api/about)
# --------------------------------------------------------------------------

def search_jooble(keyword, city):
    api_key = os.environ.get("JOOBLE_API_KEY")
    if api_key:
        resp = requests.post(
            f"https://jooble.org/api/{api_key}",
            json={"keywords": keyword, "location": city},
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        jobs = []
        for item in resp.json().get("jobs", []):
            title = clean_text(item.get("title", ""))
            url = item.get("link", "")
            if not title or not url:
                continue
            jobs.append({
                "title": title,
                "company": clean_text(item.get("company", "")),
                "location": clean_text(item.get("location", "")) or city,
                "url": canonical_url(url),
                "posted": (item.get("updated") or "")[:10] or None,
                "source": "Jooble",
            })
        return jobs

    # Without an API key, try the public Saudi site.
    slug = slugify(keyword)
    return try_urls(
        "Jooble",
        keyword,
        city,
        [
            f"https://sa.jooble.org/jobs-{slug}/{city}",
            f"https://sa.jooble.org/SearchResult?rgns={quote(city)}&ukw={quote(keyword)}",
        ],
    )


# --------------------------------------------------------------------------
# Merge + persist
# --------------------------------------------------------------------------

# Mihnati is not included: its result pages load listings purely with
# JavaScript, so there is nothing to parse from plain HTTP responses.
SOURCES = {
    "LinkedIn": search_linkedin,
    "GulfTalent": search_gulftalent,
    "Akhtaboot": search_akhtaboot,
    "Tanqeeb": search_tanqeeb,
    "Jooble": search_jooble,
}


def load_existing(data_file):
    if data_file.exists():
        with open(data_file, encoding="utf-8") as fh:
            return json.load(fh)
    return {"updated": None, "jobs": []}


def run_profile(name, keywords, cities, data_file, blocked):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = load_existing(data_file)
    by_url = {job["url"]: job for job in existing["jobs"]}

    new_count = 0
    for source, searcher in SOURCES.items():
        if source in blocked:
            continue
        for keyword in keywords:
            if source in blocked:
                break
            for city in cities:
                try:
                    results = searcher(keyword, city)[:MAX_PER_SOURCE_KEYWORD]
                except SourceBlocked as exc:
                    print(f"WARN {source} is blocking automation, skipping it today: {exc}",
                          file=sys.stderr)
                    blocked.add(source)
                    break
                except Exception as exc:  # one failing source must not kill the run
                    print(f"WARN {source} / '{keyword}' ({city}): {exc}", file=sys.stderr)
                    continue
                print(f"{source:<11} '{keyword}' ({city}): {len(results)} jobs")
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
    data_file.parent.mkdir(parents=True, exist_ok=True)
    with open(data_file, "w", encoding="utf-8") as fh:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs},
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\n{name}: {len(jobs)} jobs stored ({new_count} new today)\n")


def main():
    blocked = set()
    for name, profile in PROFILES.items():
        print(f"===== Searching for {name} =====")
        run_profile(name, profile["keywords"], profile["cities"],
                    profile["data_file"], blocked)


if __name__ == "__main__":
    main()
