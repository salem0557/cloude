"""Amazon.sa electronics deals scraper."""
import json
import logging
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal

log = logging.getLogger(__name__)

# URLs that specifically target discounted/deal products on Amazon.sa
_DEAL_URLS = [
    # Electronics with deal-type filter (Lightning Deals + Deals of the Day)
    "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031%2Cp_n_deal_type%3A16156529031",
    # Phones/mobile with deal filter
    "https://www.amazon.sa/s?i=mobile&rh=n%3A16129781031%2Cp_n_deal_type%3A16156529031",
    # Electronics with specials filter (on-sale items)
    "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031%2Cp_n_specials_match%3A21405698031",
    # Fallback: electronics sorted by price descending (some may be discounted)
    "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031&s=price-desc-rank",
]

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
        seen: set[str] = set()

        for url in _DEAL_URLS:
            resp = self._get(url, extra_headers={"Referer": "https://www.amazon.sa/"})
            if not resp:
                continue

            soup = self._soup(resp.text)
            page_title = soup.title.string.strip() if soup.title else "no title"
            log.info("  Amazon.sa page: %s | %d bytes", page_title[:80], len(resp.text))

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
            log.info("  Amazon.sa: %d result cards found on %s", len(cards), url[:70])

            if cards:
                # Log first card HTML to diagnose price selector issues
                log.info("  Amazon.sa first card (500 chars): %s", str(cards[0])[:500])

            for i, card in enumerate(cards):
                deal = self._parse_search_card(card)
                if deal:
                    if i == 0:
                        log.info(
                            "  Amazon.sa: first deal — %s | SAR %.0f → %.0f | disc %.1f%%",
                            deal.title[:50], deal.original_price, deal.sale_price, deal.discount_percent,
                        )
                    if deal.deal_id not in seen:
                        seen.add(deal.deal_id)
                        yield deal

            if seen:
                log.info("  Amazon.sa: %d deals collected from %s", len(seen), url[:70])
                break

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
            if not url or url == self.base_url:
                return None

            # Sale price: the FIRST .a-price that is NOT the strikethrough price
            # Use descendant selector (space, not >) to match nested spans
            sale_price = 0.0
            for sel in [
                "span.a-price:not(.a-text-price) span.a-offscreen",
                "span.a-price span.a-offscreen",
                ".a-price-whole",
            ]:
                el = card.select_one(sel)
                if el:
                    p = self._parse_price(el.get_text())
                    if p > 0:
                        sale_price = p
                        break

            if sale_price == 0:
                return None

            # Original / strikethrough price
            orig_price = 0.0
            for sel in [
                "span.a-text-price span.a-offscreen",
                "span.a-price.a-text-price span.a-offscreen",
                "span[data-a-strike='true'] span.a-offscreen",
            ]:
                el = card.select_one(sel)
                if el:
                    p = self._parse_price(el.get_text())
                    if p > 0:
                        orig_price = p
                        break

            # Discount badge (e.g. "Save 30%" or "-30%")
            discount = 0.0
            for badge_sel in [
                "span.a-badge-text",
                "span.savingsPercentage",
                "span[data-a-badge-color] span",
                ".a-color-price",
            ]:
                badge = card.select_one(badge_sel)
                if badge:
                    m = re.search(r"(\d+)%", badge.get_text())
                    if m:
                        discount = float(m.group(1))
                        break

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
