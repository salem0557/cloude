"""
Entry point for the Electronics Deals Telegram Bot.

Usage:
    python -m bot.main               # run once then exit
    python -m bot.main --daemon      # run on schedule (every 15 min by default)
    python -m bot.main --dry-run     # run once, print deals, don't send
    python -m bot.main --send-test   # send one sample deal to verify Telegram works
"""
import argparse
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("deals_bot")


def send_test_deal():
    """Send a hardcoded sample deal to verify the Telegram pipeline works."""
    from .models import Deal
    from . import telegram_sender

    deal = Deal(
        site_name="Amazon.sa",
        title="Samsung Galaxy S24 Ultra 256GB — Titanium Black",
        url="https://www.amazon.sa/dp/B0CMDRCZBX",
        sale_price=3299.0,
        original_price=4199.0,
        discount_percent=21.0,
        category="Phones",
        image_url="",
    )
    log.info("Sending test deal to Telegram …")
    ok = telegram_sender.send(deal)
    if ok:
        print("✅ Test deal sent! Check your Telegram group.")
    else:
        print("❌ Failed to send. Check DEALS_BOT_TOKEN and DEALS_CHANNEL_ID.")
    return ok


def run_once():
    from . import config, database, filters, telegram_sender
    from .scrapers import ALL_SCRAPERS

    database.init()
    database.purge_old(days=30)

    total_new = 0
    for ScraperClass in ALL_SCRAPERS:
        scraper = ScraperClass()
        deals = scraper.scrape()

        for deal in deals:
            if database.already_posted(deal.deal_id):
                continue
            if not filters.passes(deal):
                log.info(
                    "  Filtered: %s | disc=%.1f%% orig=%.0f sale=%.0f cat=%s",
                    deal.title[:45], deal.discount_percent,
                    deal.original_price, deal.sale_price, deal.category,
                )
                continue

            sent = telegram_sender.send(deal)
            if sent:
                database.mark_posted(deal.deal_id, deal.site_name, deal.title)
                total_new += 1
                time.sleep(1.5)  # gentle pace to respect Telegram rate limits

    log.info("Run complete — %d new deals sent.", total_new)
    return total_new


def run_daemon(interval_minutes: int):
    log.info("Daemon started — checking every %d minutes.", interval_minutes)
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Shutting down.")
            break
        except Exception as exc:
            log.error("Unexpected error in run loop: %s", exc, exc_info=True)
        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="SA Electronics Deals Telegram Bot")
    parser.add_argument("--daemon", action="store_true", help="Run on schedule")
    parser.add_argument("--dry-run", action="store_true", help="Print deals, don't send")
    parser.add_argument("--send-test", action="store_true", help="Send a sample deal to verify Telegram")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override check interval in minutes",
    )
    args = parser.parse_args()

    if args.dry_run:
        os.environ["DRY_RUN"] = "1"

    from . import config

    if args.send_test:
        sys.exit(0 if send_test_deal() else 1)

    interval = args.interval or config.CHECK_INTERVAL_MINUTES

    if args.daemon:
        run_daemon(interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
