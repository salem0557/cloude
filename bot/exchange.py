"""Exchange access layer with three modes:

  * dryrun  – no keys, no orders. Real prices via the public REST API; buys and
    sells are simulated and logged. Zero risk.
  * testnet – real orders with fake money on Binance Spot Testnet.
  * live    – real orders with REAL money. Opt-in only.

The rest of the bot talks only to this class, so the strategy/optimizer never
need to know which mode is active.
"""

from __future__ import annotations

import json
import math
import urllib.request

# Public market-data hosts, tried in order. data-api.binance.vision is the
# dedicated public data host and is the least likely to be geo/IP-blocked.
PUBLIC_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api-gcp.binance.com",
]


def _public_klines(symbol, interval, limit):
    path = (f"/api/v3/klines?symbol={symbol}"
            f"&interval={interval}&limit={limit}")
    last_err = None
    for host in PUBLIC_HOSTS:
        try:
            req = urllib.request.Request(
                host + path, headers={"User-Agent": "Mozilla/5.0 cryptobot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # try the next host
            last_err = e
    raise last_err


class Exchange:
    def __init__(self, mode, api_key=None, api_secret=None):
        self.mode = mode
        self.client = None
        self._steps = {}
        if mode in ("testnet", "live"):
            self._connect(api_key, api_secret)

    def _connect(self, key, secret):
        try:
            from binance.client import Client
        except ImportError:
            raise SystemExit(
                "Install deps first:  pip install -r bot/requirements.txt")
        key = (key or "").strip()
        secret = (secret or "").strip()
        if not key or not secret:
            raise SystemExit(
                "Set BINANCE_API_KEY and BINANCE_API_SECRET (see config.example.env).")
        # Keys must be plain ASCII. A common mistake is pasting the placeholder
        # text (e.g. the Arabic "مفتاحك") instead of the real key.
        try:
            key.encode("ascii")
            secret.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit(
                "BINANCE_API_KEY/SECRET contain non-English characters. Paste "
                "the REAL keys from Binance (English letters & digits only) — "
                "not the placeholder text.")
        try:
            self.client = Client(key, secret, testnet=(self.mode == "testnet"))
        except Exception as e:
            msg = str(e)
            hint = ""
            low = msg.lower()
            if "restricted" in low or "451" in low or "location" in low \
                    or "eligibility" in low:
                hint = ("\n→ Your server's region is geo-blocked by Binance "
                        "(e.g. Binance.com blocks US servers). Change your host's "
                        "deploy region to EU/Asia and redeploy.")
            elif "-2015" in low or "permission" in low or "api-key" in low:
                hint = ("\n→ The API key is wrong, lacks Spot-trading permission, "
                        "or is IP-restricted to a different IP. Fix it in Binance "
                        "API Management.")
            raise SystemExit(f"Could not connect to Binance: {msg}{hint}")

    # --- market data (works in every mode) ---
    def klines(self, symbol, interval, limit):
        if self.mode == "dryrun":
            data = _public_klines(symbol, interval, limit)
        else:
            data = self.client.get_klines(
                symbol=symbol, interval=interval, limit=limit)
        return data

    def closes(self, symbol, interval, limit):
        return [float(k[4]) for k in self.klines(symbol, interval, limit)]

    def ohlc(self, symbol, interval, limit):
        rows = self.klines(symbol, interval, limit)
        highs = [float(k[2]) for k in rows]
        lows = [float(k[3]) for k in rows]
        closes = [float(k[4]) for k in rows]
        return highs, lows, closes

    def last_price(self, symbol):
        if self.mode == "dryrun":
            return self.closes(symbol, "1m", 1)[-1]
        t = self.client.get_symbol_ticker(symbol=symbol)
        return float(t["price"])

    # --- lot size handling ---
    def lot_step(self, symbol):
        if symbol in self._steps:
            return self._steps[symbol]
        step = 0.0
        if self.mode in ("testnet", "live"):
            info = self.client.get_symbol_info(symbol)
            for f in (info or {}).get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
        self._steps[symbol] = step
        return step

    def _round_qty(self, qty, step):
        if step <= 0:
            return qty
        n = math.floor(qty / step)
        decimals = max(0, -int(round(math.log10(step)))) if step < 1 else 0
        return round(n * step, decimals)

    # --- orders ---
    def buy(self, symbol, quote_amount, price_hint):
        """Market buy for ``quote_amount`` of quote currency.

        Returns (fill_price, base_qty).
        """
        if self.mode == "dryrun":
            return price_hint, quote_amount / price_hint
        order = self.client.order_market_buy(
            symbol=symbol, quoteOrderQty=round(quote_amount, 2))
        qty = float(order.get("executedQty", quote_amount / price_hint))
        spent = float(order.get("cummulativeQuoteQty", quote_amount))
        price = spent / qty if qty else price_hint
        return price, qty

    def sell(self, symbol, qty, price_hint):
        """Market sell ``qty`` base. Returns (fill_price, qty_sold)."""
        if self.mode == "dryrun":
            return price_hint, qty
        qty = self._round_qty(qty, self.lot_step(symbol))
        order = self.client.order_market_sell(symbol=symbol, quantity=qty)
        got = float(order.get("cummulativeQuoteQty", price_hint * qty))
        price = got / qty if qty else price_hint
        return price, qty
