"""
Quick diagnostic — run this to verify all credentials and connectivity.

Usage:
    python -m bot.test_setup
"""
import os
import sys

import requests


def check_telegram():
    print("\n── Telegram ──────────────────────────────────────────────")
    token = os.getenv("DEALS_BOT_TOKEN", "")
    channel = os.getenv("DEALS_CHANNEL_ID", "")

    if not token:
        print("❌  DEALS_BOT_TOKEN is not set")
        return False
    if not channel:
        print("❌  DEALS_CHANNEL_ID is not set")
        return False

    # Verify the token is valid
    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    if r.status_code != 200:
        print(f"❌  Bot token is invalid (HTTP {r.status_code})")
        print(f"    Response: {r.text[:200]}")
        return False

    bot_name = r.json()["result"]["username"]
    print(f"✅  Bot token valid — @{bot_name}")

    # Send a test message to the channel
    r2 = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": channel,
            "text": "✅ Electronics Deals Bot — test message. Bot is connected and working!",
        },
        timeout=10,
    )
    if r2.status_code == 200:
        print(f"✅  Test message sent to channel {channel}")
        return True
    else:
        data = r2.json()
        desc = data.get("description", r2.text[:200])
        print(f"❌  Could not send to channel {channel}")
        print(f"    Error: {desc}")
        if "chat not found" in desc.lower():
            print("    → Make sure the channel ID starts with -100 (e.g. -1001234567890)")
            print("    → Make sure the bot is added as Admin in the channel")
        elif "bot was kicked" in desc.lower() or "member" in desc.lower():
            print("    → Add the bot as Admin in the channel first")
        return False


def check_scraper_api():
    print("\n── ScraperAPI ────────────────────────────────────────────")
    key = os.getenv("SCRAPER_API_KEY", "")

    if not key:
        print("⚠️   SCRAPER_API_KEY is not set")
        print("    Without it, only Noon's JSON API will work.")
        print("    Get a free key at https://www.scraperapi.com")
        return False

    # Test ScraperAPI with a simple request
    r = requests.get(
        "http://api.scraperapi.com",
        params={"api_key": key, "url": "https://httpbin.org/ip"},
        timeout=30,
    )
    if r.status_code == 200:
        print(f"✅  ScraperAPI key is valid")
        return True
    elif r.status_code == 401:
        print("❌  ScraperAPI key is invalid or expired")
        print("    → Go to https://www.scraperapi.com → Dashboard → copy your API key")
        print("    → Update the SCRAPER_API_KEY secret in GitHub with the correct key")
        return False
    elif r.status_code == 403:
        print("⚠️   ScraperAPI credits exhausted (free tier: 1,000/month)")
        print("    → Wait for monthly reset or upgrade your plan")
        return False
    else:
        print(f"❌  ScraperAPI test failed (HTTP {r.status_code}): {r.text[:200]}")
        return False


def check_one_site():
    print("\n── Site connectivity (Amazon.sa via ScraperAPI) ──────────")
    key = os.getenv("SCRAPER_API_KEY", "")
    if not key:
        print("⚠️   Skipped (no SCRAPER_API_KEY)")
        return

    r = requests.get(
        "http://api.scraperapi.com",
        params={
            "api_key": key,
            "url": "https://www.amazon.sa/deals",
            "country_code": "sa",
        },
        timeout=60,
    )
    if r.status_code == 200 and len(r.text) > 1000:
        print(f"✅  Amazon.sa returned {len(r.text):,} bytes of HTML")
    else:
        print(f"❌  Amazon.sa returned HTTP {r.status_code} ({len(r.text)} bytes)")


if __name__ == "__main__":
    print("Electronics Deals Bot — Setup Diagnostic")
    print("=" * 55)

    # Load .env if present
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    tg_ok = check_telegram()
    api_ok = check_scraper_api()
    if api_ok:
        check_one_site()

    print("\n── Summary ───────────────────────────────────────────────")
    if tg_ok and api_ok:
        print("✅  All good! The bot should work.")
    elif tg_ok and not api_ok:
        print("⚠️  Telegram works but ScraperAPI is missing/broken.")
        print("   Add SCRAPER_API_KEY secret → re-run the workflow.")
    elif not tg_ok:
        print("❌  Telegram is not working. Fix DEALS_BOT_TOKEN / DEALS_CHANNEL_ID first.")

    sys.exit(0 if (tg_ok and api_ok) else 1)
