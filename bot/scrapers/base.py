"""Shared utilities for all scrapers.

Uses curl_cffi to impersonate a real Chrome browser TLS fingerprint,
which bypasses Cloudflare and similar bot-protection layers that block
plain requests/urllib connections from cloud IPs.
"""
import logging
import random
import re
import time
from typing import Iterator

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cf_requests
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as cf_requests  # type: ignore[no-redef]
    _HAS_CURL_CFFI = False

from ..models import Deal
from .. import config

log = logging.getLogger(__name__)

_IMPERSONATE_VERSIONS = ["chrome110", "chrome107", "chrome120", "chrome124"]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9,ar-SA;q=0.8,ar;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class BaseScraper:
    site_name: str = ""
    base_url: str = ""

    def __init__(self):
        self._impersonate = random.choice(_IMPERSONATE_VERSIONS)
        self._ua = random.choice(_USER_AGENTS)
        if _HAS_CURL_CFFI:
            self._session = cf_requests.Session(impersonate=self._impersonate)
        else:
            import requests
            self._session = requests.Session()
        # Store base headers separately; merge per-request to avoid conflicts
        self._base_headers = {**_BASE_HEADERS, "User-Agent": self._ua}

    # ── public interface ──────────────────────────────────────────────────────

    def scrape(self) -> list[Deal]:
        log.info("Scraping %s …", self.site_name)
        try:
            deals = list(self._fetch_deals())
            log.info("  %s: %d deals found", self.site_name, len(deals))
            return deals[: config.MAX_DEALS_PER_SITE]
        except Exception as exc:
            log.error("  %s scraper failed: %s", self.site_name, exc)
            return []

    # ── subclasses override this ──────────────────────────────────────────────

    def _fetch_deals(self) -> Iterator[Deal]:
        raise NotImplementedError

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _build_headers(self, extra: dict | None = None) -> dict:
        h = dict(self._base_headers)
        if extra:
            h.update(extra)
        return h

    def _resolve_url(self, url: str, params: dict | None = None, render_js: bool = False) -> tuple[str, dict]:
        """Apply ScraperAPI proxy if configured; return (final_url, final_params)."""
        if config.SCRAPER_API_KEY:
            proxy_params = {
                "api_key": config.SCRAPER_API_KEY,
                "url": url,
                "country_code": "sa",
            }
            if render_js:
                proxy_params["render"] = "true"
            if params:
                proxy_params.update(params)
            return "http://api.scraperapi.com", proxy_params
        return url, params or {}

    def _fetch(self, url: str, extra_headers: dict | None = None, params=None, render_js: bool = False):
        """Internal: make one HTTP GET, return Response or None."""
        final_url, final_params = self._resolve_url(url, params, render_js=render_js)
        headers = self._build_headers(extra_headers)
        timeout = 90 if render_js else config.REQUEST_TIMEOUT
        if _HAS_CURL_CFFI:
            return self._session.get(
                final_url,
                headers=headers,
                params=final_params or None,
                timeout=timeout,
                impersonate=self._impersonate,
            )
        return self._session.get(
            final_url,
            headers=headers,
            params=final_params or None,
            timeout=timeout,
        )

    def _get(self, url: str, extra_headers: dict | None = None, params=None, render_js: bool = False):
        """GET with retry. Uses ScraperAPI if configured, falls back to direct curl_cffi."""
        for attempt in range(2):
            try:
                time.sleep(random.uniform(1.0, 2.5))
                resp = self._fetch(url, extra_headers=extra_headers, params=params, render_js=render_js)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (401, 403):
                    # ScraperAPI auth failure or site block — try direct curl_cffi
                    if config.SCRAPER_API_KEY and attempt == 0:
                        log.debug("  %s ScraperAPI %d — trying direct request", self.site_name, resp.status_code)
                        direct = self._fetch_direct(url, extra_headers)
                        if direct and direct.status_code == 200:
                            return direct
                    log.warning("  %s blocked (%d) on %s", self.site_name, resp.status_code, url)
                    return None
                if resp.status_code == 429:
                    log.warning("  %s rate-limited — waiting 30s", self.site_name)
                    time.sleep(30)
                    continue
                log.warning("  %s HTTP %d on %s", self.site_name, resp.status_code, url)
            except Exception as exc:
                log.warning("  %s attempt %d: %s", self.site_name, attempt + 1, exc)
            time.sleep(2 ** attempt)
        return None

    def _fetch_direct(self, url: str, extra_headers: dict | None = None):
        """Direct request bypassing ScraperAPI (uses curl_cffi TLS impersonation)."""
        headers = self._build_headers(extra_headers)
        try:
            if _HAS_CURL_CFFI:
                return self._session.get(
                    url, headers=headers,
                    timeout=config.REQUEST_TIMEOUT,
                    impersonate=self._impersonate,
                )
            import requests as _req
            return _req.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        except Exception:
            return None

    def _get_json(self, url: str, params=None, extra_headers: dict | None = None):
        """GET JSON endpoint (never uses JS rendering)."""
        merged_headers = {"Accept": "application/json, */*;q=0.9"}
        if extra_headers:
            merged_headers.update(extra_headers)
        for attempt in range(2):
            try:
                time.sleep(random.uniform(0.8, 2.0))
                resp = self._fetch(url, extra_headers=merged_headers, params=params, render_js=False)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 403:
                    log.warning("  %s API blocked (403) on %s", self.site_name, url)
                    return None
            except Exception as exc:
                log.warning("  %s JSON attempt %d: %s", self.site_name, attempt + 1, exc)
            time.sleep(2 ** attempt)
        return None

    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def _parse_price(text: str) -> float:
        """Extract float SAR price from messy strings like 'SAR 1,299.00'."""
        if not text:
            return 0.0
        cleaned = re.sub(r"[^\d.,]", "", text.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
