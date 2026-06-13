"""Jarir Bookstore (jarir.com) electronics deals scraper."""
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

_SALE_URLS = [
    "https://www.jarir.com/sa-en/computers-and-electronics/computers",
    "https://www.jarir.com/sa-en/mobile-tablets",
    "https://www.jarir.com/sa-en/audio-and-accessories",
    "https://www.jarir.com/sa-en/cameras-accessories",
    "https://www.jarir.com/sa-en/gaming",
    "https://www.jarir.com/sa-en/tv-video",
]

_JARIR_CATEGORIES = {
    "computers": "Computers & Laptops",
    "mobile": "Phones",
    "tablets": "Tablets",
    "audio": "Audio",
    "cameras": "Cameras",
    "gaming": "Gaming",
    "tv": "TVs",
}


def _cat_from_url(url: str) -> str:
    for kw, cat in _JARIR_CATEGORIES.items():
        if kw in url:
            return cat
    return "Electronics"


class JarirScraper(BaseScraper):
    site_name = "Jarir"
    base_url = "https://www.jarir.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        seen: set[str] = set()
        for url in _SALE_URLS:
            resp = self._get(
                url + f"?special_price=1&page_size={config.MAX_DEALS_PER_SITE}",
                extra_headers={"Referer": "https://www.jarir.com/sa-en/"},
                render_js=True,
            )
            if not resp:
                continue

            soup = self._soup(resp.text)
            category = _cat_from_url(url)

            # Jarir uses a Magento-based storefront
            # Product cards: .product-item, .product-items li
            cards = soup.select(
                ".products .product-item, "
                "li.product-item, "
                ".product-items .item.product"
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
                ".product-item-name a, "
                ".product-item-link, "
                "a.product-item-photo + .product-item-details a"
            )
            if not name_el:
                name_el = card.select_one("a[class*='name'], a[class*='title']")
            title = name_el.get_text(strip=True) if name_el else ""
            if not title:
                return None

            # Link
            href = name_el.get("href", "") if name_el else ""
            if card.select_one("a[href]"):
                href = href or card.select_one("a[href]")["href"]
            url = href if href.startswith("http") else self.base_url + href

            # Prices — Magento shows both old/new
            sale_el = card.select_one(
                ".special-price .price, "
                ".price-box .final-price .price, "
                "[data-price-type='finalPrice'] .price"
            )
            orig_el = card.select_one(
                ".old-price .price, "
                ".price-box .old-price .price, "
                "[data-price-type='oldPrice'] .price"
            )
            sale_price = self._parse_price(sale_el.get_text() if sale_el else "")
            orig_price = self._parse_price(orig_el.get_text() if orig_el else "")

            if sale_price == 0:
                return None

            # Discount badge
            badge = card.select_one(".discount-label, .sale-badge, [class*='discount']")
            discount = 0.0
            if badge:
                m = re.search(r"(\d+)", badge.get_text())
                if m:
                    discount = float(m.group(1))

            # Image
            img_el = card.select_one("img.product-image-photo, img")
            image_url = img_el.get("src", "") if img_el else ""

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
