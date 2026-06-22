"""Smart-money directional bias — a FREE alternative-data signal.

Binance publishes, for free on its public futures-data endpoints, the ratio of
top traders who are net long vs net short on each coin. This is a slow "where is
smart money leaning" gauge — useful as a directional confirmation, NOT as a
second-level timing tool.

``long_short_bias(symbol)`` returns ``longAccount / shortAccount`` for the top
traders (e.g. 1.8 = clearly long, 0.7 = net short), or ``None`` when the coin
has no futures market / the data can't be fetched. The bot then only treats a
buy as confirmed when smart money isn't heavily short.

Calls are cached per symbol (the data itself only updates every few minutes), so
this never adds load to the fast trading loop.
"""

from __future__ import annotations

import json
import time
import urllib.request

# Public futures-data hosts (geo-blocked the same way spot can be; list a few).
_HOSTS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]
_PERIOD = "5m"
_TTL = 300            # seconds to cache a symbol's ratio (data updates ~5m)
_CACHE = {}           # symbol -> (fetched_at, ratio_or_None)


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


def long_short_bias(symbol, ttl=_TTL):
    """Top-trader long/short account ratio for ``symbol`` (cached), or None.

    >1 means more top traders are long; <1 means net short. None means the coin
    has no futures market or the endpoint failed — the caller stays neutral."""
    now = time.time()
    hit = _CACHE.get(symbol)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    ratio = None
    try:
        rows = _get(f"/futures/data/topLongShortAccountRatio"
                    f"?symbol={symbol}&period={_PERIOD}&limit=1")
        if rows:
            ratio = float(rows[-1]["longShortRatio"])
    except Exception:
        ratio = None
    _CACHE[symbol] = (now, ratio)
    return ratio
