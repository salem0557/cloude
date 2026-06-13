"""Amazon.sa electronics deals scraper."""
import json
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal

_DEALS_URL = "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031&s=price-desc-rank&ref=sr_nr_p_n_is_sns_eligible_0"

_CATEGORY_MAP = {
    "computer": "Computers & Laptops", "laptop": "Computers & Laptops",
    "phone": "Phones", "mobile": "Phones", "iphone": "Phones", "samsung": "Phones",
    "tablet": "Tablets", "ipad": "Tablets",
    "tv": "TVs", "television": "TVs",
    "camera": "Cameras",
    "headphone": "Audio", "earphone": "Audio", "earbuds": "Audio", "speaker": "Audio", "airpods": "Audio",
    "gaming": "Gaming", "playstation": "Gaming", "xbox": "Gaming",
    "printer": "Printers", "monitor": "Monitors",
    "keyboard": "Accessories", "mouse": "Accessories", "charger": "Accessories",
}


def _guess_category(title: str) -> str:
    tl = title.lower()
    for kw, cat in _CATEGORY_MAP.items():
        if kw in tl:
            return cat
    return "Electronics"


class AmazonSAScraper(BaseScraper):
    site_name = "Amazon.sa"
    base_url = "https://www.amazon.sa"

    def _fetch_deals(self) -> Iterator[Deal]:
        resp = self._get(
            _DEALS_URL,
            extra_headers={"Referer": "https://www.amazon.sa/"},
        )
        if not resp:
            return

        soup = self._soup(resp.text)
        title = soup.title.string.strip() if soup.title else "no title"
        log.info("  Amazon.sa page: %s | %d bytes", title[:80], len(resp.text))
        seen: set[str] = set()

        # Strategy 1: JSON-LD product schema
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    deal = self._from_jsonld(item)
                    if deal and deal.deal_id not in seen:
                        seen.add(deal.deal_id)
                        yield deal
            except Exception:
                continue

        # Strategy 2: search result cards
        cards = soup.select('[data-component-type="s-search-result"]')
        for card in cards:
            deal = self._parse_search_card(card)
            if deal and deal.deal_id not in seen:
                seen.add(deal.deal_id)
                yield deal

    def _from_jsonld(self, item: dict) -> Deal | None:
        try:
            if item.get("@type") not in ("Product", "ItemList"):
                return None
            if item.get("@type") == "ItemList":
                return None

            title = item.get("name", "")
            if not title:
                return None

            url = item.get("url", item.get("@id", ""))
            if not url:
                return None

            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            sale_price = float(offers.get("price", 0))
            if sale_price == 0:
                return None

            orig_price = float(offers.get("highPrice", sale_price))
            image = item.get("image", "")
            if isinstance(image, list):
                image = image[0] if image else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=0.0,
                category=_guess_category(title),
                image_url=str(image),
            )
        except Exception:
            return None

    def _parse_search_card(self, card) -> Deal | None:
        try:
            title_el = card.select_one("h2 a span, h2 span.a-text-normal")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            link_el = card.select_one("h2 a[href]")
            href = link_el["href"] if link_el else ""
            url = (self.base_url + href if href.startswith("/") else href).split("?")[0]

            sale_el = card.select_one("span.a-price > span.a-offscreen")
            orig_el = card.select_one("span.a-price.a-text-price > span.a-offscreen")
            sale_price = self._parse_price(sale_el.get_text() if sale_el else "")
            orig_price = self._parse_price(orig_el.get_text() if orig_el else "")

            if sale_price == 0:
                return None

            badge = card.select_one("span.a-badge-text, span.savingsPercentage")
            discount = 0.0
            if badge:
                m = re.search(r"(\d+)%", badge.get_text())
                if m:
                    discount = float(m.group(1))

            img_el = card.select_one("img.s-image")
            image_url = img_el.get("src", "") if img_el else ""

            return Deal(
                site_name=self.site_name,
                title=title,
                url=url,
                sale_price=sale_price,
                original_price=orig_price,
                discount_percent=discount,
                category=_guess_category(title),
                image_url=image_url,
            )
        except Exception:
            return None
