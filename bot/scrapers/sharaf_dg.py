"""SharafDG.com Saudi Arabia electronics deals scraper.

ScraperAPI (basic tier) CAN access SharafDG — gets HTTP 200 with full Magento HTML.
The page includes JSON-LD (CollectionPage + ItemList) with product URLs and prices,
which is the most reliable extraction strategy.
"""
import json
import logging
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal
from .. import config

log = logging.getLogger(__name__)

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

_CAT_FROM_TITLE = {
    "phone": "Phones", "mobile": "Phones", "samsung": "Phones",
    "laptop": "Computers & Laptops", "computer": "Computers & Laptops",
    "tv": "TVs", "television": "TVs",
    "camera": "Cameras",
    "headphone": "Audio", "earphone": "Audio", "earbuds": "Audio", "speaker": "Audio",
    "gaming": "Gaming", "playstation": "Gaming", "xbox": "Gaming",
    "tablet": "Tablets",
}


def _cat_from_url(url: str) -> str:
    low = url.lower()
    for kw, cat in _SHARAF_CATEGORIES.items():
        if kw in low:
            return cat
    return "Electronics"


def _cat_from_title(title: str, default: str = "Electronics") -> str:
    low = title.lower()
    for kw, cat in _CAT_FROM_TITLE.items():
        if kw in low:
            return cat
    return default


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
                break

            soup = self._soup(resp.text)
            category = _cat_from_url(url)
            log.info("  SharafDG: %d bytes from %s", len(resp.text), url.split("/sa/en/")[-1])

            # Strategy 1: JSON-LD — SharafDG embeds CollectionPage/ItemList with product data
            ld_deals = 0
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    for deal in self._parse_jsonld(data, category):
                        if deal.deal_id not in seen:
                            seen.add(deal.deal_id)
                            ld_deals += 1
                            yield deal
                except Exception:
                    continue
            if ld_deals:
                log.info("  SharafDG: %d deals from JSON-LD on %s", ld_deals, url.split("/")[-1])
                continue

            # Strategy 2: product card CSS selectors (Magento + custom themes)
            cards = soup.select(
                ".product-item, "
                ".product_list_item, "
                "[class*='ProductCard'], "
                "li[class*='product'], "
                "article[class*='product'], "
                "[data-product-id], "
                ".product-item-info, "
                "form[data-product-sku]"
            )
            log.info("  SharafDG: %d CSS cards on %s", len(cards), url.split("/")[-1])
            for card in cards:
                deal = self._parse_card(card, category)
                if deal and deal.deal_id not in seen:
                    seen.add(deal.deal_id)
                    yield deal

    def _parse_jsonld(self, data: dict, default_cat: str) -> Iterator[Deal]:
        dtype = data.get("@type", "")
        if dtype == "Product":
            deal = self._product_from_ld(data, default_cat)
            if deal:
                yield deal
        elif dtype in ("CollectionPage", "ItemList"):
            main = data.get("mainEntity", data)
            items = main.get("itemListElement", main.get("items", main.get("item", [])))
            for entry in (items if isinstance(items, list) else [items]):
                inner = entry.get("item", entry) if isinstance(entry, dict) else {}
                yield from self._parse_jsonld(inner, default_cat)
        elif dtype == "ListItem":
            inner = data.get("item", data)
            yield from self._parse_jsonld(inner, default_cat)

    def _product_from_ld(self, item: dict, default_cat: str) -> Deal | None:
        try:
            title = item.get("name", "")
            if not title:
                return None
            url = item.get("url", item.get("@id", ""))
            if not url or not url.startswith("http"):
                return None
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            sale_price = float(offers.get("price", 0))
            if sale_price == 0:
                return None
            orig_price = float(offers.get("highPrice", offers.get("price", sale_price)))
            image = item.get("image", "")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=0.0,
                category=_cat_from_title(title, default_cat),
                image_url=str(image),
            )
        except Exception:
            return None

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
