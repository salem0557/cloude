"""Job-board scraping logic shared with the GitHub Pages scraper.

Adapted from ``scraper/search_jobs.py`` so the same parsers power both the
website and the Apify actor. The difference: every searcher takes a
:class:`ScrapeContext` carrying a ``requests.Session``, so Apify proxies flow
through automatically, and the functions only *return* job dicts -- writing to
the Apify dataset is the actor's job.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("riyadh-jobs")

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


@dataclass
class ScrapeContext:
    """Everything a searcher needs that isn't the keyword/city pair."""

    session: requests.Session
    country: str = "Saudi Arabia"
    jooble_api_key: str | None = None


def make_session(proxy_url: str | None = None) -> requests.Session:
    """A requests session with browser headers and (optionally) an Apify proxy."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def matches_keyword(title: str, keyword: str) -> bool:
    """True when the job title shares at least one word with the keyword."""
    tokens = re.findall(r"[A-Za-z]+", keyword)
    return any(
        re.search(rf"\b{re.escape(t)}\b", title, re.IGNORECASE)
        for t in tokens
        if len(t) >= 2
    )


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def canonical_url(url: str) -> str:
    """Strip query string / fragment so the same job always dedupes."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch(ctx: ScrapeContext, url, *, params=None, headers=None, timeout=REQUEST_TIMEOUT):
    resp = ctx.session.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


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
            # (the page is already filtered to a city/country search).
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


def try_urls(ctx, source, keyword, city, urls, extra_parser=None):
    """Fetch candidate URLs until one yields jobs relevant to the keyword.

    Raises :class:`SourceBlocked` when every URL fails at the network level, so
    the caller can skip the source's remaining keywords for this run.
    """
    errors = []
    for url in urls:
        try:
            resp = fetch(ctx, url)
        except requests.Timeout as exc:
            errors.append(exc)
            log.info("%s: %s -> timeout", source, url)
            continue
        except requests.RequestException as exc:
            errors.append(exc)
            log.info("%s: %s -> %s", source, url, exc)
            continue
        jobs = parse_jsonld_jobs(resp.text, resp.url, source, city)
        if not jobs and extra_parser:
            jobs = extra_parser(resp, keyword, city)
        # Sites sometimes ignore unknown search parameters and return their
        # newest jobs instead, so keep only titles related to the keyword.
        jobs = [j for j in jobs if matches_keyword(j["title"], keyword)]
        if jobs:
            return jobs
    if errors and len(errors) == len(urls):
        raise SourceBlocked(f"{source} refused all requests: {errors[-1]}")
    return []


# --------------------------------------------------------------------------
# LinkedIn (public guest job feed, no login required)
# --------------------------------------------------------------------------

def search_linkedin(ctx, keyword, city):
    jobs = []
    for start in (0, 25):
        resp = fetch(
            ctx,
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
            params={
                "keywords": keyword,
                "location": f"{city}, {ctx.country}",
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


def search_gulftalent(ctx, keyword, city):
    slug = slugify(keyword)
    country_slug = slugify(ctx.country)
    return try_urls(
        ctx,
        "GulfTalent",
        keyword,
        city,
        [
            f"https://www.gulftalent.com/{country_slug}/jobs/title/{slug}",
            f"https://www.gulftalent.com/jobs/search?keywords={quote(keyword)}&country={country_slug}",
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


def search_akhtaboot(ctx, keyword, city):
    return try_urls(
        ctx,
        "Akhtaboot",
        keyword,
        city,
        [
            f"https://www.akhtaboot.com/en/jobs/search?q={quote(keyword)}&country={quote(ctx.country)}",
            f"https://www.akhtaboot.com/en/jobs/search?keywords={quote(keyword)}&country={quote(ctx.country)}&city={quote(city)}",
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


def search_tanqeeb(ctx, keyword, city):
    slug = slugify(keyword)
    cityslug = city.lower()
    country_slug = slugify(ctx.country)
    return try_urls(
        ctx,
        "Tanqeeb",
        keyword,
        city,
        [
            f"https://saudi.tanqeeb.com/en/jobs/search?keywords={quote(keyword)}&state={cityslug}",
            f"https://www.tanqeeb.com/en/{country_slug}/{slug}-jobs-in-{cityslug}",
            f"https://www.tanqeeb.com/en/jobs/search?keywords={quote(keyword)}&country={country_slug}",
        ],
        extra_parser=parse_tanqeeb_links,
    )


# --------------------------------------------------------------------------
# Jooble (job aggregator; official free API at jooble.org/api/about)
# --------------------------------------------------------------------------

def search_jooble(ctx, keyword, city):
    if ctx.jooble_api_key:
        resp = ctx.session.post(
            f"https://jooble.org/api/{ctx.jooble_api_key}",
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
        ctx,
        "Jooble",
        keyword,
        city,
        [
            f"https://sa.jooble.org/jobs-{slug}/{city}",
            f"https://sa.jooble.org/SearchResult?rgns={quote(city)}&ukw={quote(keyword)}",
        ],
    )


# Mihnati is not included: its result pages load listings purely with
# JavaScript, so there is nothing to parse from plain HTTP responses.
SOURCES = {
    "LinkedIn": search_linkedin,
    "GulfTalent": search_gulftalent,
    "Akhtaboot": search_akhtaboot,
    "Tanqeeb": search_tanqeeb,
    "Jooble": search_jooble,
}
