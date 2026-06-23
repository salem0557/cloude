"""Social-momentum signal — FREE (CoinGecko trending, no API key).

CoinGecko publishes the coins users are searching for most right now
(/search/trending). A coin trading on the bot's shortlist that is ALSO trending
socially has a fresh attention/momentum tailwind — a useful *confirming* nudge,
never a veto (we don't want to chase hype blindly, and the bot already wants more
candidates, not fewer).

``trending_symbols()`` returns a set of base assets (e.g. {"SOL","SAGA"}).
``is_trending(symbol)`` matches a trading pair like "SAGAUSDT" against it.
Cached and degrades to an empty set on any failure (everything stays neutral).
"""

from __future__ import annotations

import json
import time
import urllib.request

_URL = "https://api.coingecko.com/api/v3/search/trending"
_TTL = 900
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD")
_CACHE = {"t": 0.0, "syms": set()}


def trending_symbols(ttl=_TTL):
    now = time.time()
    if _CACHE["syms"] and (now - _CACHE["t"]) < ttl:
        return _CACHE["syms"]
    try:
        req = urllib.request.Request(_URL, headers={"User-Agent": "cryptobot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        syms = set()
        for c in d.get("coins", []):
            sym = (c.get("item", {}).get("symbol") or "").upper()
            if sym:
                syms.add(sym)
        if syms:
            _CACHE.update(t=now, syms=syms)
        return syms
    except Exception:
        return _CACHE["syms"]


def _base(symbol):
    s = symbol.upper()
    for q in _QUOTES:
        if s.endswith(q):
            return s[: -len(q)]
    return s


def is_trending(symbol):
    return _base(symbol) in trending_symbols()
