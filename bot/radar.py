"""Coin-selection radar — FREE, no API key. Sharpens WHICH coins and strategies
the advisor favours with leading, cross-sectional signals the bot was missing:

  * relative strength — is the coin outperforming BTC? Cross-sectional momentum is
    one of crypto's most robust selection factors (winners keep winning short-term).
  * volume surge — real moves come with volume; quiet 'breakouts' are usually traps.
  * order-book imbalance — live bid vs ask pressure: who is leaning in right now.
  * efficiency ratio — Kaufman's trend-vs-chop gauge on BTC, so the bot prefers
    trend strategies when the market trends and mean-reversion when it ranges.

Everything is cached / degrades to neutral on any failure, like the other feeds.
"""

from __future__ import annotations

import time

from exchange import _public_get

_OBI_TTL = 300
_OBI = {}            # symbol -> (fetched_at, ratio_or_None)


def efficiency_ratio(closes, n=24):
    """Kaufman Efficiency Ratio over the last ``n`` bars: |net move| / total path.
    ~1 = clean trend, ~0 = choppy/ranging. 0.0 if not enough data."""
    if not closes or len(closes) <= n:
        return 0.0
    change = abs(closes[-1] - closes[-1 - n])
    path = sum(abs(closes[i] - closes[i - 1])
               for i in range(len(closes) - n, len(closes)))
    return (change / path) if path else 0.0


def relative_strength(coin_closes, ref_closes, bars=24):
    """Coin's return MINUS the reference (BTC) return over ``bars``, in %.
    Positive = outperforming BTC. None if not enough data."""
    if (not coin_closes or not ref_closes
            or len(coin_closes) <= bars or len(ref_closes) <= bars):
        return None
    if coin_closes[-1 - bars] == 0 or ref_closes[-1 - bars] == 0:
        return None
    c = coin_closes[-1] / coin_closes[-1 - bars] - 1.0
    r = ref_closes[-1] / ref_closes[-1 - bars] - 1.0
    return (c - r) * 100


def volume_surge(vols, n=20):
    """Latest volume vs its recent average (0.5 = +50%). 0 if unavailable."""
    if not vols or len(vols) < n + 1:
        return 0.0
    window = [v for v in vols[-n - 1:-1] if v]
    avg = (sum(window) / len(window)) if window else 0.0
    return (vols[-1] / avg - 1.0) if avg else 0.0


def orderbook_imbalance(symbol, levels=20, ttl=_OBI_TTL):
    """Sum(bid qty)/Sum(ask qty) over the top ``levels`` (cached). >1 = more
    resting buy interest (buy pressure); <1 = sell pressure. None on failure."""
    now = time.time()
    hit = _OBI.get(symbol)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = None
    try:
        d = _public_get(f"/api/v3/depth?symbol={symbol}&limit={levels}")
        bids = sum(float(q) for _, q in d.get("bids", []))
        asks = sum(float(q) for _, q in d.get("asks", []))
        val = (bids / asks) if asks else None
    except Exception:
        val = None
    _OBI[symbol] = (now, val)
    return val
