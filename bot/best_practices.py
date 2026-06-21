"""Live "best-practices" market-regime gauge.

Beyond raw price signals, good crypto practice is to read the *environment*:
breaking negative news (hacks, bans, lawsuits) and crowd sentiment (the Fear &
Greed index). Every cycle the bot consults this module and adapts:

  * strongly negative breaking news  -> pause NEW buys (only manage exits)
  * extreme greed                    -> trade smaller (reduce position size)
  * extreme fear                     -> allow buys (contrarian "buy the dip")

Everything degrades gracefully: if the news file or the network is unavailable
the regime is simply "neutral" and the bot trades normally.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEWS_FILE = HERE.parent / "docs" / "crypto" / "data" / "news.json"
FNG_URL = "https://api.alternative.me/fng/?limit=1"

NEGATIVE = ["hack", "exploit", "breach", "scam", "fraud", "lawsuit", "sue",
            "sued", "ban", "bans", "banned", "crackdown", "crash", "plunge",
            "plummet", "dump", "sell-off", "selloff", "collapse", "bankrupt",
            "liquidation", "liquidated", "charges", "halt", "delist",
            "rug", "ponzi", "tumble", "slump", "fear"]
POSITIVE = ["etf approval", "approve", "approved", "surge", "rally", "soar",
            "soars", "adoption", "partnership", "bullish", "all-time high",
            "record high", "gains", "rebound", "upgrade", "inflows",
            "institutional", "breakout", "halving"]


def _news_sentiment():
    """Net sentiment score from recent headlines (negative<0<positive)."""
    try:
        data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None, 0
    items = data.get("news", [])[:30]
    score = 0
    for it in items:
        text = f"{it.get('title','')} {it.get('summary','')}".lower()
        score += sum(1 for w in POSITIVE if w in text)
        score -= sum(1 for w in NEGATIVE if w in text)
    return score, len(items)


def _fear_greed():
    """Fetch the Fear & Greed index (0-100) or None."""
    try:
        req = urllib.request.Request(
            FNG_URL, headers={"User-Agent": "cryptobot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        v = d.get("data", [{}])[0]
        return int(v.get("value")), v.get("value_classification")
    except Exception:
        return None, None


def get_regime():
    """Return the current market regime and how it should affect trading."""
    sentiment, n_news = _news_sentiment()
    fng, fng_label = _fear_greed()

    allow_buys = True
    risk_multiplier = 1.0
    reasons = []

    if sentiment is not None and sentiment <= -4:
        allow_buys = False
        reasons.append(f"أخبار سلبية قوية (مؤشّر {sentiment})")
    elif sentiment is not None and sentiment >= 4:
        reasons.append(f"أخبار إيجابية (مؤشّر {sentiment})")

    if fng is not None:
        if fng >= 85:
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append(f"طمع شديد ({fng}) — تصغير الحجم")
        elif fng <= 20:
            reasons.append(f"خوف شديد ({fng}) — فرص شراء")

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "news_sentiment": sentiment,
        "news_count": n_news,
        "fear_greed": fng,
        "fear_greed_label": fng_label,
        "allow_buys": allow_buys,
        "risk_multiplier": risk_multiplier,
        "reason": " | ".join(reasons) or "وضع طبيعي",
    }
