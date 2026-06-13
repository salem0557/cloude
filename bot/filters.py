"""Filter deals against user-configured criteria."""
from .models import Deal
from . import config


def passes(deal: Deal) -> bool:
    # Minimum discount
    if deal.discount_percent < config.MIN_DISCOUNT_PERCENT:
        return False

    # Price range
    if deal.sale_price < config.MIN_PRICE_SAR:
        return False
    if config.MAX_PRICE_SAR > 0 and deal.sale_price > config.MAX_PRICE_SAR:
        return False

    # Category whitelist
    if config.ALLOWED_CATEGORIES:
        if not any(
            cat.lower() in deal.category.lower()
            for cat in config.ALLOWED_CATEGORIES
        ):
            return False

    # Keyword requirement
    if config.REQUIRED_KEYWORDS:
        title_lower = deal.title.lower()
        if not any(kw.lower() in title_lower for kw in config.REQUIRED_KEYWORDS):
            return False

    return True
