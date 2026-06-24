"""Telegram push notifications (free) for the advisor's buy recommendations.

Set two env vars (no cost):
  TELEGRAM_BOT_TOKEN  from @BotFather (create a bot, copy the token)
  TELEGRAM_CHAT_ID    your chat id (message the bot, or @userinfobot gives it)

Degrades to a silent no-op when unset, so the bot runs fine without it.
"""

from __future__ import annotations

import json
import os
import urllib.request


def configured():
    return bool((os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
                and (os.environ.get("TELEGRAM_CHAT_ID") or "").strip())


def send(text):
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.load(r).get("ok"))
    except Exception:
        return False
