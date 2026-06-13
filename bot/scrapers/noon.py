"""Noon.com (Saudi Arabia) electronics deals scraper.

Noon uses a React SPA, but their product listing API is public and
returns clean JSON.  We call the search/catalog endpoint with:
  - Channel: SA
  - Sort by discount (high→low)
  - Category: Electronics
  - Min discount filter
"""
import logging
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

log = logging.getLogger(__name__)

# Noon's internal catalog API
_API = "https://www.noon.com/api/v3/u/catalog/?app=consumer&version=v2"

_CATEGORY_NODE_MAP = {
    "Computers & Tablets": "Computers & Tablets",
    "Mobile & Tablets": "Phones",
    "TV & Video": "TVs",
    "Audio": "Audio",
    "Cameras & Accessories": "Cameras",
    "Gaming": "Gaming",
    "Printers & Accessories": "Printers",
    "Computer Accessories": "Accessories",
    "Smart Devices": "Smart Devices",
}


def _map_category(raw: str) -> str:
    for key, val in _CATEGORY_NODE_MAP.items():
        if key.lower() in raw.lower():
            return val
    return raw or "Electronics"


class NoonScraper(BaseScraper):
    site_name = "Noon"
    base_url = "https://www.noon.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        # Try the internal API first; fall back to HTML scraping
        yield from self._via_api()

    def _via_api(self) -> Iterator[Deal]:
        """Use Noon's JSON catalog API (electronics, sorted by discount)."""
        params = {
            "q": "",
            "limit": config.MAX_DEALS_PER_SITE,
            "offset": "0",
            "sort_by": "discount",
            "channel": "desktop-web",
            "country": "SA",
            "lang": "en",
            "cat": "electronics",
            "f[discount_percent][min]": str(int(config.MIN_DISCOUNT_PERCENT)),
        }

        # Noon needs specific headers or it returns 403
        headers = {
            "x-country-code": "SA",
            "x-locale": "en",
            "x-channel": "web",
            "Referer": "https://www.noon.com/saudi-en/electronics/",
        }

        data = self._get_json(_API, params=params, extra_headers=headers)
        if not data:
            # Fall back to HTML scraping of the deals listing
            yield from self._via_html()
            return

        items = []
        if isinstance(data, dict):
            items = data.get("hits", data.get("items", []))
        elif isinstance(data, list):
            items = data

        for item in items:
            deal = self._parse_api_item(item)
            if deal:
                yield deal

    def _parse_api_item(self, item: dict) -> Deal | None:
        try:
            title = item.get("name", item.get("title", ""))
            if not title:
                return None

            sku = item.get("sku", item.get("id", ""))
            url = f"https://www.noon.com/saudi-en/{sku}/" if sku else item.get("url", "")
            if not url:
                return None

            prices = item.get("price", {})
            if isinstance(prices, dict):
                sale_price = float(prices.get("now", prices.get("sale_price", 0)))
                orig_price = float(prices.get("was", prices.get("regular_price", 0)))
            else:
                sale_price = float(item.get("sale_price", item.get("price", 0)))
                orig_price = float(item.get("regular_price", item.get("original_price", 0)))

            if sale_price == 0:
                return None

            discount = float(item.get("discount_percent", item.get("discount", 0)))
            category = _map_category(item.get("category_name", item.get("category", "")))
            image_url = item.get("image", item.get("thumbnail", ""))
            if isinstance(image_url, list):
                image_url = image_url[0] if image_url else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=discount,
                category=category,
                image_url=str(image_url),
            )
        except Exception as exc:
            log.debug("Noon parse error: %s", exc)
            return None

    def _via_html(self) -> Iterator[Deal]:
        """Fallback: scrape Noon's electronics sale page HTML."""
        url = (
            f"https://www.noon.com/saudi-en/electronics/"
            f"?limit={config.MAX_DEALS_PER_SITE}&sort_by=discount"
            f"&f[discount_percent][min]={int(config.MIN_DISCOUNT_PERCENT)}"
        )
        resp = self._get(url, extra_headers={"Referer": "https://www.noon.com/"})
        if not resp:
            return

        soup = self._soup(resp.text)
        # Noon renders product cards with class names like "productContainer" or "[data-qa='product-name']"
        cards = soup.select("[data-qa='product-card'], .productContainer, article.sc-")
        for card in cards:
            deal = self._parse_html_card(card)
            if deal:
                yield deal

    def _parse_html_card(self, card) -> Deal | None:
        try:
            title_el = card.select_one("[data-qa='product-name'], .name, h3")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = self.base_url + href if href.startswith("/") else href

            now_el = card.select_one("[data-qa='price-now'], .priceNow")
            was_el = card.select_one("[data-qa='price-was'], .priceWas")
            sale_price = self._parse_price(now_el.get_text() if now_el else "")
            orig_price = self._parse_price(was_el.get_text() if was_el else "")

            if sale_price == 0:
                return None

            badge_el = card.select_one("[data-qa='discount'], .discount")
            discount = 0.0
            if badge_el:
                import re
                m = re.search(r"(\d+)", badge_el.get_text())
                if m:
                    discount = float(m.group(1))

            img_el = card.select_one("img")
            image_url = img_el.get("src", "") if img_el else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=discount,
                category="Electronics",
                image_url=image_url,
            )
        except Exception:
            return None
