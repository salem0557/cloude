"""eXtra (extra.com) Saudi Arabia electronics deals scraper."""
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

_OFFERS_URLS = [
    "https://www.extra.com/en-sa/mobile-tablets/smartphones",
    "https://www.extra.com/en-sa/laptops-computers/laptops",
    "https://www.extra.com/en-sa/audio/headphones-earphones",
    "https://www.extra.com/en-sa/televisions",
    "https://www.extra.com/en-sa/gaming",
    "https://www.extra.com/en-sa/cameras",
]

_EXTRA_CATEGORIES = {
    "mobile": "Phones",
    "smartphone": "Phones",
    "laptop": "Computers & Laptops",
    "computer": "Computers & Laptops",
    "audio": "Audio",
    "headphone": "Audio",
    "television": "TVs",
    "tv": "TVs",
    "gaming": "Gaming",
    "camera": "Cameras",
    "tablet": "Tablets",
}


def _cat_from_url(url: str) -> str:
    low = url.lower()
    for kw, cat in _EXTRA_CATEGORIES.items():
        if kw in low:
            return cat
    return "Electronics"


class ExtraScraper(BaseScraper):
    site_name = "Extra"
    base_url = "https://www.extra.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        seen: set[str] = set()
        for url in _OFFERS_URLS:
            resp = self._get(
                url + f"?onSale=true&pageSize={config.MAX_DEALS_PER_SITE}",
                extra_headers={"Referer": "https://www.extra.com/en-sa/"},
            )
            if not resp:
                break  # All Extra URLs share the same domain/WAF — stop on first block

            soup = self._soup(resp.text)
            category = _cat_from_url(url)

            # eXtra typically uses SAP Hybris storefront
            cards = soup.select(
                ".product-list-item, "
                ".js-productTile, "
                ".product-tile, "
                "[class*='ProductCard'], "
                "article[class*='product']"
            )

            for card in cards:
                deal = self._parse_card(card, category)
                if deal and deal.deal_id not in seen:
                    seen.add(deal.deal_id)
                    yield deal

    def _parse_card(self, card, category: str) -> Deal | None:
        try:
            # Title
            name_el = card.select_one(
                ".product-name a, "
                ".product-title a, "
                "[class*='name'] a, "
                "h2 a, h3 a"
            )
            if not name_el:
                name_el = card.select_one(".product-name, .product-title, h2, h3")
            title = (
                name_el.get("title") or name_el.get_text(strip=True)
                if name_el else ""
            )
            if not title:
                return None

            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = href if href.startswith("http") else self.base_url + href

            # Prices
            sale_el = card.select_one(
                ".sale-price, .special-price, "
                "[class*='CurrentPrice'], "
                "[class*='salePrice'], "
                ".priceContainer [class*='current']"
            )
            orig_el = card.select_one(
                ".original-price, .regular-price, .was-price, "
                "[class*='WasPrice'], [class*='oldPrice']"
            )
            sale_price = self._parse_price(sale_el.get_text() if sale_el else "")
            orig_price = self._parse_price(orig_el.get_text() if orig_el else "")

            if sale_price == 0:
                # Try data attributes
                sale_price = self._parse_price(card.get("data-price", ""))

            if sale_price == 0:
                return None

            # Discount badge
            discount = 0.0
            badge = card.select_one(
                ".discount, .badge-sale, [class*='Discount'], "
                "[class*='discount-badge']"
            )
            if badge:
                m = re.search(r"(\d+)", badge.get_text())
                if m:
                    discount = float(m.group(1))

            img_el = card.select_one("img[src], img[data-src]")
            image_url = ""
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src", "")

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=discount,
                category=category,
                image_url=image_url,
            )
        except Exception:
            return None
