"""
Central configuration — loaded once from environment variables / .env file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)


def _list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [v.strip() for v in raw.split(",") if v.strip()]


# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("DEALS_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("DEALS_CHANNEL_ID", "")

# ── Scheduling ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

# ── Filters ───────────────────────────────────────────────────────────────────
MIN_DISCOUNT_PERCENT: float = float(os.getenv("MIN_DISCOUNT_PERCENT", "15"))
MIN_PRICE_SAR: float = float(os.getenv("MIN_PRICE_SAR", "0"))
MAX_PRICE_SAR: float = float(os.getenv("MAX_PRICE_SAR", "0"))  # 0 = no limit

# Comma-separated category whitelist — empty means allow all
ALLOWED_CATEGORIES: list[str] = _list("ALLOWED_CATEGORIES")

# Comma-separated keywords — empty means allow all
REQUIRED_KEYWORDS: list[str] = _list("REQUIRED_KEYWORDS")

# ── Scraping ──────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_DEALS_PER_SITE: int = int(os.getenv("MAX_DEALS_PER_SITE", "30"))

# ── Storage ───────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).parent / "deals.db"))

# ── Proxy / ScraperAPI ────────────────────────────────────────────────────────
# Optional: ScraperAPI key (https://www.scraperapi.com — free tier: 1000 req/month)
# When set, all requests are routed through ScraperAPI's residential proxy network,
# bypassing Cloudflare blocks that affect cloud/datacenter IPs.
SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "")

# ── Misc ──────────────────────────────────────────────────────────────────────
# Set to "1" to print messages instead of sending them to Telegram
DRY_RUN: bool = os.getenv("DRY_RUN", "0") == "1"
