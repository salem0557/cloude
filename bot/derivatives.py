"""Binance futures derivatives signals — FREE alternative data (no API key).

Price alone is a rear-view mirror. These three public futures-data feeds measure
LEVERAGE, POSITIONING and AGGRESSIVE ORDER FLOW — leading/confirming context the
bot was previously blind to:

  * funding rate   — who pays whom to hold a perp. Strongly positive = crowded,
                     leveraged longs (reversal risk). Negative = crowded shorts.
  * open interest  — total perp positions open. Rising OI + rising price = real
                     trend with fresh money; rising OI + falling price = building
                     shorts. Falling OI = positions closing (trend exhausting).
  * taker ratio    — ratio of market (aggressive) BUY vs SELL volume. >1 = buyers
                     are lifting offers right now (short-term demand).

``snapshot(symbol)`` returns a small dict (all keys may be None when the coin has
no futures market or the endpoint is geo-blocked) plus a combined, explainable
``confirm_long`` flag the bot uses as a soft buy gate. Everything is cached and
degrades to neutral on any failure, exactly like smart_money.py.
"""

from __future__ import annotations

import json
import time
import urllib.request

# Same public futures hosts as smart_money (geo-blocked the same way spot can be).
_HOSTS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]
_PERIOD = "5m"
_TTL = 300                 # cache a symbol's snapshot for 5m (data updates ~5m)
_CACHE = {}                # symbol -> (fetched_at, snapshot_dict)

# Funding rate is per 8h. ~0.01% (0.0001) is the neutral baseline; above
# HIGH_FUNDING longs are crowded/expensive (caution), above EXTREME it's froth.
HIGH_FUNDING = 0.0005
EXTREME_FUNDING = 0.0010


def _get(path):
    last = None
    for host in _HOSTS:
        try:
            req = urllib.request.Request(
                host + path, headers={"User-Agent": "Mozilla/5.0 cryptobot/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.load(r)
        except Exception as e:
            last = e
    raise last


def _funding(symbol):
    """Last funding rate (e.g. 0.0001 = 0.01%/8h), or None."""
    try:
        d = _get(f"/fapi/v1/premiumIndex?symbol={symbol}")
        if isinstance(d, list):
            d = d[0] if d else {}
        return float(d["lastFundingRate"])
    except Exception:
        return None


def _oi_change(symbol, limit=12):
    """Recent open-interest % change over ``limit`` periods, or None.

    Positive = positions building; negative = positions unwinding."""
    try:
        rows = _get(f"/futures/data/openInterestHist?symbol={symbol}"
                    f"&period={_PERIOD}&limit={limit}")
        if not rows or len(rows) < 2:
            return None
        first = float(rows[0]["sumOpenInterest"])
        last = float(rows[-1]["sumOpenInterest"])
        return (last / first - 1.0) if first else None
    except Exception:
        return None


def _taker_ratio(symbol):
    """Aggressive taker buy/sell volume ratio (>1 = net buying), or None."""
    try:
        rows = _get(f"/futures/data/takerlongshortRatio?symbol={symbol}"
                    f"&period={_PERIOD}&limit=1")
        if rows:
            return float(rows[-1]["buySellRatio"])
    except Exception:
        return None
    return None


def snapshot(symbol, ttl=_TTL):
    """Combined derivatives view for ``symbol`` (cached).

    Returns a dict: funding, oi_change, taker_ratio (each float or None),
    score (-1..1 directional lean), confirm_long (bool), reason (str).
    """
    now = time.time()
    hit = _CACHE.get(symbol)
    if hit and (now - hit[0]) < ttl:
        return hit[1]

    funding = _funding(symbol)
    oi = _oi_change(symbol)
    taker = _taker_ratio(symbol)

    score = 0.0
    reasons = []
    confirm_long = True

    if funding is not None:
        if funding >= EXTREME_FUNDING:
            score -= 0.5
            confirm_long = False           # euphoric crowded longs — don't chase
            reasons.append(f"funding مرتفع جداً {funding*100:.3f}% (شراء مزدحم)")
        elif funding >= HIGH_FUNDING:
            score -= 0.2
            reasons.append(f"funding مرتفع {funding*100:.3f}%")
        elif funding < 0:
            score += 0.15                  # shorts crowded — mild contrarian long
            reasons.append(f"funding سالب {funding*100:.3f}% (شورت مزدحم)")

    if taker is not None:
        if taker >= 1.05:
            score += 0.3
            reasons.append(f"تدفّق شراء {taker:.2f}")
        elif taker <= 0.95:
            score -= 0.3
            reasons.append(f"تدفّق بيع {taker:.2f}")

    if oi is not None:
        # OI confirms direction: rising OI with buying = real trend.
        if oi > 0.01 and (taker is None or taker >= 1.0):
            score += 0.2
            reasons.append(f"OI صاعد {oi*100:+.1f}%")
        elif oi < -0.02:
            score -= 0.1
            reasons.append(f"OI هابط {oi*100:+.1f}%")

    score = max(-1.0, min(1.0, score))
    snap = {
        "funding": funding,
        "oi_change": oi,
        "taker_ratio": taker,
        "score": round(score, 3),
        "confirm_long": confirm_long,
        "reason": " | ".join(reasons) or "—",
    }
    _CACHE[symbol] = (now, snap)
    return snap
