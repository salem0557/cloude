"""Live crypto news headlines — FREE (CryptoCompare public news feed).

The bot's news gate previously read only a static docs/.../news.json that can go
stale on a long-running deploy. This pulls fresh headlines straight from
CryptoCompare's free news endpoint (no key required; an optional CRYPTOCOMPARE_KEY
raises limits) so sentiment always reflects the last hour of the market.

``headlines()`` returns a list of {title, body, source, categories}. Cached for
``ttl`` seconds and degrades to the last good list (or empty) on any failure, so
callers always stay neutral / never crash.
"""

from __future__ import annotations

import json
import time
import urllib.request

_URL = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
_TTL = 600
_CACHE = {"t": 0.0, "items": []}


def headlines(api_key=None, ttl=_TTL, limit=40):
    now = time.time()
    if _CACHE["items"] and (now - _CACHE["t"]) < ttl:
        return _CACHE["items"]
    url = _URL + (f"&api_key={api_key}" if api_key else "")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cryptobot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        items = []
        for a in d.get("Data", [])[:limit]:
            items.append({
                "title": a.get("title", "") or "",
                "body": (a.get("body", "") or "")[:300],
                "source": a.get("source", "") or "",
                "categories": a.get("categories", "") or "",
            })
        if items:
            _CACHE["t"] = now
            _CACHE["items"] = items
        return items
    except Exception:
        return _CACHE["items"]
