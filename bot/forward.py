"""Forward-looking risk signal — FREE (Deribit DVOL, no API key).

Most feeds are backward-looking (what already happened). Deribit's DVOL index is
different: it's the options market's EXPECTED 30-day volatility for BTC — a true
forward read of how much turbulence traders are pricing in (crypto's "VIX").

  * high DVOL  → market expects big moves / stress → trade SMALLER (risk-off)
  * low  DVOL  → calm expected → normal sizing

``expected_vol()`` returns {dvol, score (-1..1), reason}. Cached and degrades to a
neutral score of 0 on any failure, so it never blocks trading.
"""

from __future__ import annotations

import json
import time
import urllib.request

_URL = ("https://www.deribit.com/api/v2/public/get_volatility_index_data"
        "?currency=BTC&resolution=43200")
_TTL = 3600
_CACHE = {"t": 0.0, "result": {"dvol": None, "score": 0.0, "reason": "—"}}

# BTC DVOL (annualised %). ~40-60 is typical; above HIGH the market is bracing
# for turbulence, below LOW it expects calm.
HIGH_DVOL = 75.0
LOW_DVOL = 40.0


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "cryptobot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def expected_vol(ttl=_TTL):
    now = time.time()
    if (now - _CACHE["t"]) < ttl and _CACHE["result"]["reason"] != "—":
        return _CACHE["result"]
    result = {"dvol": None, "score": 0.0, "reason": "—"}
    try:
        end = int(now * 1000)
        start = end - 3 * 24 * 3600 * 1000
        d = _get(f"{_URL}&start_timestamp={start}&end_timestamp={end}")
        rows = d.get("result", {}).get("data", [])
        if rows:
            dvol = float(rows[-1][4])          # [ts, open, high, low, close]
            result["dvol"] = round(dvol, 1)
            if dvol >= HIGH_DVOL:
                result["score"] = -0.3
                result["reason"] = (f"DVOL {dvol:.0f} مرتفع — السوق يتوقّع "
                                    f"اضطراباً (تصغير الحجم)")
            elif dvol <= LOW_DVOL:
                result["score"] = 0.1
                result["reason"] = f"DVOL {dvol:.0f} هادئ (تذبذب متوقّع منخفض)"
            else:
                result["reason"] = f"DVOL {dvol:.0f} طبيعي"
            _CACHE.update(t=now, result=result)
    except Exception:
        pass
    return result
