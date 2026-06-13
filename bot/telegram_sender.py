"""Format and send deal messages to the Telegram channel."""
import logging
import time

import requests

from .models import Deal
from . import config

log = logging.getLogger(__name__)

_SITE_EMOJI = {
    "Amazon.sa": "🛒",
    "Noon": "🌙",
    "Jarir": "📚",
    "Extra": "⚡",
    "SharafDG": "💎",
}


def _escape(text: str) -> str:
    """Escape MarkdownV2 special chars."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _format(deal: Deal) -> str:
    emoji = _SITE_EMOJI.get(deal.site_name, "🏷️")
    lines = [
        f"{emoji} *{_escape(deal.site_name)}*",
        "",
        f"📦 {_escape(deal.title)}",
        "",
    ]

    if deal.original_price > 0 and deal.original_price != deal.sale_price:
        lines.append(
            f"💰 ~SAR {deal.original_price:,.0f}~ → *SAR {deal.sale_price:,.0f}*"
        )
    else:
        lines.append(f"💰 *SAR {deal.sale_price:,.0f}*")

    if deal.discount_percent > 0:
        lines.append(f"📉 *{deal.discount_percent:.0f}% OFF*")

    if deal.category:
        lines.append(f"🗂️ {_escape(deal.category)}")

    lines += ["", f"[🛒 View Deal]({deal.url})"]
    return "\n".join(lines)


def send(deal: Deal) -> bool:
    """Send one deal to the configured Telegram channel. Returns True on success."""
    text = _format(deal)

    if config.DRY_RUN:
        print("─" * 60)
        print(f"[DRY RUN] {deal.site_name} | {deal.title}")
        print(f"  SAR {deal.sale_price:,.0f}  ({deal.discount_percent:.0f}% off)")
        print(f"  {deal.url}")
        return True

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
        log.warning("Telegram credentials not configured — set DEALS_BOT_TOKEN and DEALS_CHANNEL_ID")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }

    # Optional: attach image via sendPhoto instead
    if deal.image_url:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": config.TELEGRAM_CHANNEL_ID,
            "photo": deal.image_url,
            "caption": text,
            "parse_mode": "MarkdownV2",
        }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:               # flood control
                retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
                log.warning("Telegram rate limit — sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue
            log.error("Telegram error %s: %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            log.warning("Telegram send attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 ** attempt)

    return False
