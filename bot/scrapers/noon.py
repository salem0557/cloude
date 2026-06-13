"""Noon.com (Saudi Arabia) electronics deals scraper.

Primary: Noon's internal catalog search API (JSON, no JS rendering needed).
Fallback: JS-rendered HTML page.
"""
import json
import logging
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

log = logging.getLogger(__name__)

# Noon's search API — works without authentication
_SEARCH_API = "https://www.noon.com/api/v3/u/catalog/"

_CAT_MAP = {
    "mobile": "Phones", "phone": "Phones", "smartphone": "Phones",
    "laptop": "Computers & Laptops", "computer": "Computers & Laptops",
    "tablet": "Tablets", "ipad": "Tablets",
    "tv": "TVs", "television": "TVs",
    "headphone": "Audio", "earphone": "Audio", "speaker": "Audio", "earbuds": "Audio",
    "camera": "Cameras",
    "gaming": "Gaming",
    "watch": "Wearables",
}


def _cat(name: str) -> str:
    low = name.lower()
    for k, v in _CAT_MAP.items():
        if k in low:
            return v
    return "Electronics"


class NoonScraper(BaseScraper):
    site_name = "Noon"
    base_url = "https://www.noon.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        # Try the JSON API first (fast, no JS rendering)
        yield from self._via_search_api()

    def _via_search_api(self) -> Iterator[Deal]:
        params = {
            "app": "consumer",
            "version": "v2",
            "q": "",
            "limit": str(config.MAX_DEALS_PER_SITE),
            "offset": "0",
            "sort_by": "discount",
            "channel": "desktop-web",
            "country": "SA",
            "lang": "en",
        }
        headers = {
            "x-country-code": "SA",
            "x-locale": "en",
            "x-channel": "web",
            "Referer": "https://www.noon.com/saudi-en/electronics/",
            "Origin": "https://www.noon.com",
        }

        # Try multiple category slugs
        for cat_slug in ["electronics", "mobiles-tablets", "computers-accessories", "televisions-video"]:
            params["cat"] = cat_slug
            data = self._get_json(_SEARCH_API, params=params, extra_headers=headers)
            if not data:
                continue
            hits = []
            if isinstance(data, dict):
                hits = data.get("hits", data.get("items", data.get("products", [])))
            for item in hits:
                deal = self._parse_item(item)
                if deal:
                    yield deal

    def _parse_item(self, item: dict) -> Deal | None:
        try:
            title = item.get("name", item.get("title", ""))
            if not title:
                return None

            sku = item.get("sku", item.get("id", ""))
            url = f"https://www.noon.com/saudi-en/-p/{sku}/" if sku else item.get("url", "")
            if not url:
                return None

            prices = item.get("price", {})
            if isinstance(prices, dict):
                sale_price = float(prices.get("now", prices.get("sale_price", prices.get("selling", 0))))
                orig_price = float(prices.get("was", prices.get("regular_price", prices.get("original", 0))))
            else:
                sale_price = float(item.get("sale_price", item.get("price", item.get("sellingPrice", 0))))
                orig_price = float(item.get("regular_price", item.get("original_price", item.get("mrp", 0))))

            if sale_price == 0:
                return None

            discount = float(item.get("discount_percent", item.get("discount", item.get("discountPercent", 0))))

            cat_raw = item.get("category_name", item.get("category", item.get("primaryCategory", "")))
            category = _cat(str(cat_raw) + " " + title)

            image = item.get("image", item.get("thumbnail", item.get("imageUrl", "")))
            if isinstance(image, list):
                image = image[0] if image else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=discount,
                category=category,
                image_url=str(image),
            )
        except Exception:
            return None
