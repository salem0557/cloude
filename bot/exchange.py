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


def _public_get(path):
    """GET a public Binance endpoint, trying each host in turn."""
    last_err = None
    for host in PUBLIC_HOSTS:
        try:
            req = urllib.request.Request(
                host + path, headers={"User-Agent": "Mozilla/5.0 cryptobot/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as e:  # try the next host
            last_err = e
    raise last_err


def _public_klines(symbol, interval, limit):
    return _public_get(f"/api/v3/klines?symbol={symbol}"
                       f"&interval={interval}&limit={limit}")


# Leveraged-token / wrapped suffixes to keep out of the auto universe.
_BAD_SUFFIX = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
_STABLES = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "DAIUSDT",
            "USDPUSDT", "EURUSDT", "AEURUSDT", "USD1USDT"}


def usdt_universe(min_quote_volume=5_000_000.0, max_n=250):
    """Discover tradable USDT spot pairs, filtered by 24h volume.

    Returns symbols sorted by 24h quote volume (most liquid first). Excludes
    leveraged tokens and stablecoin pairs. min_quote_volume=0 + a large max_n
    gives essentially the whole board.
    """
    info = _public_get("/api/v3/exchangeInfo")
    tradable = set()
    for s in info.get("symbols", []):
        sym = s.get("symbol", "")
        if (s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
                and s.get("isSpotTradingAllowed")
                and not sym.endswith(_BAD_SUFFIX) and sym not in _STABLES):
            tradable.add(sym)
    # rank by liquidity using one bulk 24h ticker call
    rows = _public_get("/api/v3/ticker/24hr")
    vols = []
    for t in rows:
        sym = t.get("symbol", "")
        if sym in tradable:
            try:
                vols.append((sym, float(t.get("quoteVolume", 0))))
            except (TypeError, ValueError):
                pass
    vols.sort(key=lambda x: x[1], reverse=True)
    out = [sym for sym, v in vols if v >= min_quote_volume]
    return out[:max_n] if max_n else out


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

    # --- account (live/testnet only) ---
    def account_summary(self):
        """Real balance from Binance: free USDT and total portfolio value in
        USDT. Returns None in dryrun; raises on a Binance API error so the
        caller can log the exact reason (permission / IP / etc.)."""
        if self.mode == "dryrun" or not self.client:
            return None
        acct = self.client.get_account()
        tickers = self.client.get_all_tickers()
        price = {t["symbol"]: float(t["price"]) for t in tickers}
        free_usdt = 0.0
        total = 0.0
        for b in acct.get("balances", []):
            amt = float(b["free"]) + float(b["locked"])
            if amt <= 0:
                continue
            asset = b["asset"]
            if asset == "USDT":
                free_usdt = float(b["free"])
                total += amt
            else:
                p = price.get(asset + "USDT")
                if p:
                    total += amt * p
        return {"free_usdt": round(free_usdt, 2),
                "total_usdt": round(total, 2)}

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

    def ohlcv(self, symbol, interval, limit):
        """highs, lows, closes, volumes — volume (k[5]) was previously thrown
        away; it's a strong, free confirmation feature (real moves come with
        volume; quiet 'breakouts' are usually traps)."""
        rows = self.klines(symbol, interval, limit)
        highs = [float(k[2]) for k in rows]
        lows = [float(k[3]) for k in rows]
        closes = [float(k[4]) for k in rows]
        volumes = [float(k[5]) for k in rows]
        return highs, lows, closes, volumes

    def last_price(self, symbol):
        if self.mode == "dryrun":
            return self.closes(symbol, "1m", 1)[-1]
        t = self.client.get_symbol_ticker(symbol=symbol)
        return float(t["price"])

    def spread_pct(self, symbol):
        """Best bid/ask spread as a % of price (liquidity / escape gauge).

        A wide spread means you'd buy high and sell low — hard to exit cleanly.
        Returns None if it can't be fetched (caller then allows the trade)."""
        try:
            d = _public_get(f"/api/v3/ticker/bookTicker?symbol={symbol}")
            bid, ask = float(d["bidPrice"]), float(d["askPrice"])
            if bid > 0:
                return (ask - bid) / bid * 100
        except Exception:
            return None
        return None

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
        # Cap the spend to the USDT we actually have (avoids -2010 on the buy).
        free = self.free_balance("USDT")
        if free > 0 and quote_amount > free:
            quote_amount = free * 0.997      # leave a hair for fees/rounding
        if quote_amount < 1:
            raise RuntimeError(f"insufficient USDT to buy {symbol} (free={free})")
        order = self.client.order_market_buy(
            symbol=symbol, quoteOrderQty=round(quote_amount, 2))
        qty = float(order.get("executedQty", quote_amount / price_hint))
        spent = float(order.get("cummulativeQuoteQty", quote_amount))
        price = spent / qty if qty else price_hint
        return price, qty

    def free_balance(self, asset):
        """Free (sellable) balance of a base asset; 0.0 in dryrun/on error."""
        if self.mode == "dryrun" or not self.client:
            return 0.0
        try:
            bal = self.client.get_asset_balance(asset=asset)
            return float(bal["free"]) if bal else 0.0
        except Exception:
            return 0.0

    def sell(self, symbol, qty, price_hint):
        """Market sell ``qty`` base. Returns (fill_price, qty_sold).

        Caps the quantity to the asset we actually own — Binance takes a small
        trading fee out of the bought amount, so selling the full recorded qty
        would fail with -2010 (insufficient balance). If Binance still rejects
        the order for balance/min-size reasons it raises RuntimeError so the
        caller drops the position from tracking instead of looping forever.
        """
        if self.mode == "dryrun":
            return price_hint, qty
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        step = self.lot_step(symbol)
        free = self.free_balance(base)
        if free > 0:
            qty = min(qty, free)
        qty = self._round_qty(qty, step)
        if qty <= 0:
            raise RuntimeError(f"nothing to sell for {symbol} (free={free})")
        try:
            order = self.client.order_market_sell(symbol=symbol, quantity=qty)
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            # -2010 / insufficient: fee + rounding left a hair less than recorded.
            # Re-read the real free balance, shave to a clean lot, and retry once.
            if "-2010" in msg or "insufficient" in low:
                free = self.free_balance(base)
                qty = self._round_qty(free * 0.999, step)
                if qty <= 0:
                    raise RuntimeError(
                        f"insufficient balance to sell {symbol} (free={free})")
                order = self.client.order_market_sell(symbol=symbol, quantity=qty)
            # -1013 / NOTIONAL: position value is below Binance's minimum sell
            # size (dust). It can't be market-sold; tell the caller to drop it.
            elif "-1013" in msg or "notional" in low or "min" in low:
                raise RuntimeError(
                    f"{symbol} is below Binance's minimum sell size (dust) — "
                    f"can't market-sell {qty}")
            else:
                raise
        got = float(order.get("cummulativeQuoteQty", price_hint * qty))
        price = got / qty if qty else price_hint
        return price, qty
