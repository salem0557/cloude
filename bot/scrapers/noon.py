"""Noon.com (Saudi Arabia) electronics deals scraper.

Uses Noon's internal catalog search API which returns JSON directly.
No JS rendering needed — the API endpoint is public.
"""
import logging
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

log = logging.getLogger(__name__)

_API_BASE = "https://www.noon.com/api/v1/u/catalog/"

_CATEGORIES = [
    ("electronics",             "Electronics"),
    ("mobiles-tablets",         "Phones"),
    ("computers-accessories",   "Computers & Laptops"),
    ("televisions-video",       "TVs"),
    ("audio",                   "Audio"),
    ("gaming",                  "Gaming"),
    ("cameras-accessories",     "Cameras"),
]

_CAT_MAP = {
    "mobile": "Phones", "phone": "Phones", "smartphone": "Phones", "iphone": "Phones",
    "laptop": "Computers & Laptops", "computer": "Computers & Laptops", "macbook": "Computers & Laptops",
    "tablet": "Tablets", "ipad": "Tablets",
    "tv": "TVs", "television": "TVs",
    "headphone": "Audio", "earphone": "Audio", "speaker": "Audio", "earbuds": "Audio", "airpods": "Audio",
    "camera": "Cameras",
    "gaming": "Gaming", "playstation": "Gaming", "xbox": "Gaming",
    "watch": "Wearables",
}


def _cat(title: str, default: str = "Electronics") -> str:
    low = title.lower()
    for k, v in _CAT_MAP.items():
        if k in low:
            return v
    return default


class NoonScraper(BaseScraper):
    site_name = "Noon"
    base_url = "https://www.noon.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        seen: set[str] = set()
        for cat_slug, cat_label in _CATEGORIES:
            for deal in self._fetch_category(cat_slug, cat_label):
                if deal.deal_id not in seen:
                    seen.add(deal.deal_id)
                    yield deal
            if len(seen) >= config.MAX_DEALS_PER_SITE:
                break

    def _fetch_category(self, cat_slug: str, cat_label: str) -> Iterator[Deal]:
        params = {
            "app": "consumer",
            "version": "v2",
            "q": "",
            "limit": "30",
            "offset": "0",
            "sort_by": "discount",
            "channel": "desktop-web",
            "country": "SA",
            "lang": "en",
            "cat": cat_slug,
            f"f[discount_percent][min]": str(int(config.MIN_DISCOUNT_PERCENT)),
        }
        headers = {
            "Referer": f"https://www.noon.com/saudi-en/{cat_slug}/",
            "x-country-code": "SA",
            "x-locale": "en",
            "x-channel": "web",
            "Accept": "application/json, */*",
        }

        data = self._get_json(_API_BASE, params=params, extra_headers=headers)
        if not data:
            log.warning("Noon: no data returned for category %s", cat_slug)
            return

        # Log the actual response structure to identify the right keys
        if isinstance(data, dict):
            log.info("  Noon API keys [%s]: %s", cat_slug, list(data.keys())[:15])
        elif isinstance(data, list):
            log.info("  Noon API list [%s]: %d items", cat_slug, len(data))

        # Noon API wraps results differently depending on version
        hits = []
        if isinstance(data, dict):
            hits = (
                data.get("hits") or
                data.get("products") or
                data.get("items") or
                data.get("results") or
                (data.get("data", {}) or {}).get("hits") or
                (data.get("data", {}) or {}).get("products") or
                []
            )
        elif isinstance(data, list):
            hits = data

        for item in hits:
            deal = self._parse(item, cat_label)
            if deal:
                yield deal

    def _parse(self, item: dict, default_cat: str) -> Deal | None:
        try:
            title = item.get("name") or item.get("title") or item.get("product_name", "")
            if not title:
                return None

            sku = item.get("sku") or item.get("id") or item.get("product_id", "")
            url = (
                item.get("url") or
                item.get("product_url") or
                (f"https://www.noon.com/saudi-en/-p/{sku}/" if sku else "")
            )
            if not url:
                return None

            # Price — Noon uses various shapes
            price_data = item.get("price") or {}
            if isinstance(price_data, dict):
                sale = float(price_data.get("now") or price_data.get("sale_price") or
                             price_data.get("selling_price") or price_data.get("current") or 0)
                orig = float(price_data.get("was") or price_data.get("original_price") or
                             price_data.get("mrp") or price_data.get("regular") or sale)
            else:
                sale = float(item.get("sale_price") or item.get("selling_price") or
                             item.get("price") or 0)
                orig = float(item.get("original_price") or item.get("mrp") or sale)

            if sale == 0:
                return None

            discount = float(
                item.get("discount_percent") or item.get("discount") or
                item.get("discount_percentage") or 0
            )

            image = item.get("image") or item.get("thumbnail") or item.get("image_url") or ""
            if isinstance(image, list):
                image = image[0] if image else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale,
                original_price=orig,
                discount_percent=discount,
                category=_cat(title, default_cat),
                image_url=str(image),
            )
        except Exception as exc:
            log.debug("Noon parse error: %s", exc)
            return None
