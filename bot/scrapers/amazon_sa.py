"""Amazon.sa electronics deals scraper."""
import re
from typing import Iterator

from .base import BaseScraper
from ..models import Deal

# Amazon's goldbox deals page filtered to electronics
_DEALS_URLS = [
    "https://www.amazon.sa/deals?ref=nav_cs_gb",
    "https://www.amazon.sa/s?i=electronics&rh=n%3A16129781031&s=price-desc-rank&deals-widget=%7B%22version%22%3A1%2C%22dpFilters%22%3A%5B%7B%22field%22%3A%22dealEligibility%22%2C%22value%22%3A%22%22%7D%5D%7D",
]

_CATEGORY_MAP = {
    "computer": "Computers & Laptops",
    "laptop": "Computers & Laptops",
    "phone": "Phones",
    "mobile": "Phones",
    "tablet": "Tablets",
    "tv": "TVs",
    "camera": "Cameras",
    "headphone": "Audio",
    "earphone": "Audio",
    "speaker": "Audio",
    "gaming": "Gaming",
    "printer": "Printers",
    "monitor": "Monitors",
    "keyboard": "Accessories",
    "mouse": "Accessories",
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
            _DEALS_URLS[0],
            extra_headers={"Referer": "https://www.amazon.sa/"},
        )
        if not resp:
            return

        soup = self._soup(resp.text)
        seen: set[str] = set()

        # ── strategy 1: search result cards ──────────────────────────────────
        cards = soup.select('[data-component-type="s-search-result"]')
        for card in cards:
            deal = self._parse_search_card(card)
            if deal and deal.deal_id not in seen:
                seen.add(deal.deal_id)
                yield deal

        # ── strategy 2: deal tiles (goldbox / today's deals layout) ──────────
        if not seen:
            tiles = soup.select(".DealContent, [data-testid='deal-card'], .a-section.dealTile")
            for tile in tiles:
                deal = self._parse_tile(tile)
                if deal and deal.deal_id not in seen:
                    seen.add(deal.deal_id)
                    yield deal

    # ── card parsers ──────────────────────────────────────────────────────────

    def _parse_search_card(self, card) -> Deal | None:
        try:
            # Title
            title_el = card.select_one("h2 a span, h2 span.a-text-normal")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            # Link
            link_el = card.select_one("h2 a[href]")
            href = link_el["href"] if link_el else ""
            url = self.base_url + href if href.startswith("/") else href
            url = url.split("?")[0]  # strip tracking params

            # Prices
            sale_el = card.select_one("span.a-price > span.a-offscreen")
            orig_el = card.select_one("span.a-price.a-text-price > span.a-offscreen")
            sale_price = self._parse_price(sale_el.get_text() if sale_el else "")
            orig_price = self._parse_price(orig_el.get_text() if orig_el else "")

            if sale_price == 0:
                return None

            # Discount badge
            badge = card.select_one("span.a-badge-text, span.savingsPercentage")
            discount = 0.0
            if badge:
                m = re.search(r"(\d+)%", badge.get_text())
                if m:
                    discount = float(m.group(1))

            # Image
            img_el = card.select_one("img.s-image, img[data-image-index]")
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

    def _parse_tile(self, tile) -> Deal | None:
        try:
            title_el = tile.select_one("a[title], .dealTitle, .a-text-normal")
            title = (
                title_el.get("title") or title_el.get_text(strip=True)
                if title_el else ""
            )
            if not title:
                return None

            link_el = tile.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = self.base_url + href if href.startswith("/") else href

            price_els = tile.select("span.a-price span.a-offscreen, .dealPrice")
            prices = [self._parse_price(el.get_text()) for el in price_els if el.get_text()]
            prices = [p for p in prices if p > 0]

            sale_price = min(prices) if prices else 0.0
            orig_price = max(prices) if len(prices) > 1 else 0.0
            if sale_price == 0:
                return None

            badge = tile.select_one("span.a-badge-text, .savingsPercentage")
            discount = 0.0
            if badge:
                m = re.search(r"(\d+)%", badge.get_text())
                if m:
                    discount = float(m.group(1))

            img_el = tile.select_one("img")
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
