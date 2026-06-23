"""On-chain risk signal — FREE (DeFiLlama, no API key).

True per-coin exchange-netflow / whale tracking needs a paid feed (CryptoQuant,
Nansen, Glassnode — all well above a small budget). The best *free* on-chain
proxy for overall risk appetite is where capital actually sits on-chain:

  * Total DeFi TVL trend (api.llama.fi) — capital flowing INTO smart contracts
    (rising TVL) = on-chain risk-on; a sharp multi-day drain = risk-off.

``market_signal()`` returns {tvl_change_7d, score (-1..1), reason}. Cached and
degrades to a neutral score of 0 on any failure, so it never blocks trading.
This complements (does not replace) the futures/derivatives per-coin signals.
"""

from __future__ import annotations

import json
import time
import urllib.request

_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl"
_TTL = 3600
_CACHE = {"t": 0.0, "result": {"tvl_change_7d": None, "score": 0.0, "reason": "—"}}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "cryptobot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def market_signal(ttl=_TTL):
    now = time.time()
    if (now - _CACHE["t"]) < ttl and _CACHE["result"]["reason"] != "—":
        return _CACHE["result"]
    result = {"tvl_change_7d": None, "score": 0.0, "reason": "—"}
    try:
        rows = _get(_TVL_URL)              # [{date, tvl}, ...] daily, ascending
        if isinstance(rows, list) and len(rows) >= 8:
            last = float(rows[-1]["tvl"])
            prev = float(rows[-8]["tvl"])  # ~7 days ago
            if prev:
                chg = last / prev - 1.0
                result["tvl_change_7d"] = round(chg, 4)
                if chg >= 0.05:
                    result["score"] = 0.25
                    result["reason"] = f"TVL +{chg*100:.1f}%/7d (تدفّق رأس مال on-chain)"
                elif chg <= -0.07:
                    result["score"] = -0.3
                    result["reason"] = f"TVL {chg*100:.1f}%/7d (هروب رأس مال — حذر)"
                else:
                    result["reason"] = f"TVL {chg*100:+.1f}%/7d (مستقر)"
        if result["reason"] != "—":
            _CACHE.update(t=now, result=result)
    except Exception:
        pass
    return result
