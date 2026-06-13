"""SharafDG.com Saudi Arabia electronics deals scraper."""
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

_DEALS_URLS = [
    "https://www.sharafdg.com/sa/en/mobile-phones-tablets/smartphones",
    "https://www.sharafdg.com/sa/en/computers/laptops",
    "https://www.sharafdg.com/sa/en/television-video/televisions",
    "https://www.sharafdg.com/sa/en/audio-devices/headphones-earphones",
    "https://www.sharafdg.com/sa/en/gaming",
    "https://www.sharafdg.com/sa/en/cameras-accessories/digital-cameras",
]

_SHARAF_CATEGORIES = {
    "mobile": "Phones",
    "smartphone": "Phones",
    "laptop": "Computers & Laptops",
    "computer": "Computers & Laptops",
    "television": "TVs",
    "audio": "Audio",
    "headphone": "Audio",
    "gaming": "Gaming",
    "camera": "Cameras",
    "tablet": "Tablets",
}


def _cat_from_url(url: str) -> str:
    low = url.lower()
    for kw, cat in _SHARAF_CATEGORIES.items():
        if kw in low:
            return cat
    return "Electronics"


class SharafDGScraper(BaseScraper):
    site_name = "SharafDG"
    base_url = "https://www.sharafdg.com"

    def _fetch_deals(self) -> Iterator[Deal]:
        seen: set[str] = set()
        for url in _DEALS_URLS:
            resp = self._get(
                url + f"?discounted=1&page_size={config.MAX_DEALS_PER_SITE}",
                extra_headers={"Referer": "https://www.sharafdg.com/sa/en/"},
            )
            if not resp:
                break  # All SharafDG URLs share the same domain/WAF — stop on first block

            soup = self._soup(resp.text)
            category = _cat_from_url(url)

            cards = soup.select(
                ".product-item, "
                ".product_list_item, "
                "[class*='ProductCard'], "
                "li[class*='product'], "
                "article[class*='product']"
            )

            for card in cards:
                deal = self._parse_card(card, category)
                if deal and deal.deal_id not in seen:
                    seen.add(deal.deal_id)
                    yield deal

    def _parse_card(self, card, category: str) -> Deal | None:
        try:
            name_el = card.select_one(
                ".product-name a, .product-title a, "
                "h2 a, h3 a, .name a, [class*='title'] a"
            )
            if not name_el:
                name_el = card.select_one(".product-name, h2, h3")
            title = (
                name_el.get("title") or name_el.get_text(strip=True)
                if name_el else ""
            )
            if not title:
                return None

            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = href if href.startswith("http") else self.base_url + href

            sale_el = card.select_one(
                ".special-price .price, .sale-price, "
                "[class*='FinalPrice'], [class*='salePrice'], "
                ".price-box .minimal-price .price"
            )
            orig_el = card.select_one(
                ".old-price .price, .was-price, "
                "[class*='OldPrice'], [class*='regularPrice']"
            )
            sale_price = self._parse_price(sale_el.get_text() if sale_el else "")
            orig_price = self._parse_price(orig_el.get_text() if orig_el else "")

            if sale_price == 0:
                return None

            discount = 0.0
            badge = card.select_one(".discount-percent, .offer-badge, [class*='discount']")
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
