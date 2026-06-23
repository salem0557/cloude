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
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import news_feed
import news_ai
import onchain

HERE = Path(__file__).resolve().parent
NEWS_FILE = HERE.parent / "docs" / "crypto" / "data" / "news.json"
FNG_URL = "https://api.alternative.me/fng/?limit=1"
# CoinGecko free global endpoint — BTC dominance gauges alt risk appetite:
# rising/high dominance = money rotating OUT of alts into BTC (headwind for
# alt longs), so the bot trades alts smaller when dominance is elevated.
CG_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
HIGH_DOMINANCE = 58.0

NEGATIVE = ["hack", "exploit", "breach", "scam", "fraud", "lawsuit", "sue",
            "sued", "ban", "bans", "banned", "crackdown", "crash", "plunge",
            "plummet", "dump", "sell-off", "selloff", "collapse", "bankrupt",
            "liquidation", "liquidated", "charges", "halt", "delist",
            "rug", "ponzi", "tumble", "slump", "fear"]
POSITIVE = ["etf approval", "approve", "approved", "surge", "rally", "soar",
            "soars", "adoption", "partnership", "bullish", "all-time high",
            "record high", "gains", "rebound", "upgrade", "inflows",
            "institutional", "breakout", "halving"]


def _collect_headlines():
    """Merge the static news.json with the live CryptoCompare feed (free).

    Live headlines are added only when NEWS_FEED_LIVE is on (default) so news is
    never stale on a long-running deploy. Returns a list of {title, summary}.
    """
    items = []
    try:
        data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
        for it in data.get("news", [])[:30]:
            items.append({"title": it.get("title", ""),
                          "summary": it.get("summary", "")})
    except Exception:
        pass
    live_on = (os.environ.get("NEWS_FEED_LIVE", "true") or "").lower() \
        in ("1", "true", "yes", "on")
    if live_on:
        for h in news_feed.headlines(os.environ.get("CRYPTOCOMPARE_KEY")):
            items.append({"title": h.get("title", ""),
                          "summary": h.get("body", "")})
    return items


def _keyword_sentiment(items):
    """Net keyword sentiment over headlines (negative<0<positive)."""
    if not items:
        return None
    score = 0
    for it in items:
        text = f"{it.get('title','')} {it.get('summary','')}".lower()
        score += sum(1 for w in POSITIVE if w in text)
        score -= sum(1 for w in NEGATIVE if w in text)
    return score


def _news_sentiment():
    """Net sentiment score + count. Uses a free LLM (Gemini/Groq) to READ the
    headlines when a key is set; otherwise falls back to keyword counting. The
    LLM score (-1..1) is rescaled to the same integer band the rest of the
    regime logic expects so thresholds keep working either way.
    """
    items = _collect_headlines()
    if not items:
        return None, 0, "—"
    llm_score, llm_reason = news_ai.sentiment(items)
    if llm_score is not None:
        # map [-1,1] -> roughly [-8,8] to match the keyword thresholds (±4)
        return round(llm_score * 8), len(items), f"AI: {llm_reason}"
    return _keyword_sentiment(items), len(items), "keyword"


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


def _btc_dominance():
    """BTC market-cap dominance % from CoinGecko (free), or None."""
    try:
        req = urllib.request.Request(
            CG_GLOBAL_URL, headers={"User-Agent": "cryptobot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        return float(d["data"]["market_cap_percentage"]["btc"])
    except Exception:
        return None


def get_regime():
    """Return the current market regime and how it should affect trading."""
    sentiment, n_news, news_src = _news_sentiment()
    fng, fng_label = _fear_greed()
    dominance = _btc_dominance()
    chain = onchain.market_signal()

    allow_buys = True
    risk_multiplier = 1.0
    reasons = []

    if sentiment is not None and sentiment <= -4:
        allow_buys = False
        reasons.append(f"أخبار سلبية قوية ({news_src} {sentiment})")
    elif sentiment is not None and sentiment >= 4:
        reasons.append(f"أخبار إيجابية ({news_src} {sentiment})")

    if fng is not None:
        if fng >= 85:
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append(f"طمع شديد ({fng}) — تصغير الحجم")
        elif fng <= 20:
            reasons.append(f"خوف شديد ({fng}) — فرص شراء")

    if dominance is not None and dominance >= HIGH_DOMINANCE:
        risk_multiplier = min(risk_multiplier, 0.7)
        reasons.append(f"هيمنة BTC مرتفعة ({dominance:.1f}%) — ضغط على العملات البديلة")

    # On-chain capital flow (free DeFiLlama TVL trend): a sharp multi-day drain
    # is a risk-off tell → trade smaller; steady inflow just adds context.
    if chain.get("score", 0) <= -0.25:
        risk_multiplier = min(risk_multiplier, 0.7)
        reasons.append(chain["reason"])
    elif chain.get("reason", "—") != "—":
        reasons.append(chain["reason"])

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "news_sentiment": sentiment,
        "news_count": n_news,
        "news_source": news_src,
        "fear_greed": fng,
        "fear_greed_label": fng_label,
        "btc_dominance": dominance,
        "tvl_change_7d": chain.get("tvl_change_7d"),
        "allow_buys": allow_buys,
        "risk_multiplier": risk_multiplier,
        "reason": " | ".join(reasons) or "وضع طبيعي",
    }
