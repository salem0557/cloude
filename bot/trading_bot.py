#!/usr/bin/env python3
"""A small, safe educational crypto trading bot for Binance Spot.

Strategy: SMA crossover (a "fast" moving average crossing a "slow" one).
  * Fast SMA crosses ABOVE slow  -> BUY  (open a long position)
  * Fast SMA crosses BELOW slow  -> SELL (close the position)
  * Optional stop-loss closes the position if price drops too far.

Three modes (set with BOT_MODE), from safest to riskiest:
  * dryrun  (default) – never touches the exchange; simulates fills and
    just prints what it WOULD do. Use this to learn with zero risk.
  * testnet – trades on Binance's Spot Testnet with FAKE money.
  * live    – trades with REAL money. You must opt in explicitly.

This is an educational tool, NOT financial advice. Trading bots can and do
lose money. Start in dryrun, then testnet, and only ever risk money you can
afford to lose.
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"
TRADES_CSV = HERE / "trades.csv"


# ----------------------------- configuration -----------------------------
def load_env():
    """Load KEY=VALUE pairs from bot/.env (if present) into os.environ."""
    env_path = HERE / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def cfg(name, default=None):
    return os.environ.get(name, default)


# ------------------------------- helpers ---------------------------------
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


def sma(values, n):
    return sum(values[-n:]) / n


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"position": None, "entry_price": 0.0, "base_qty": 0.0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_trade(side, price, qty, mode):
    new = not TRADES_CSV.exists()
    with TRADES_CSV.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "mode", "side", "price", "qty", "quote_value"])
        w.writerow([now(), mode, side, f"{price:.8f}", f"{qty:.8f}", f"{price * qty:.4f}"])


def round_step(qty, step):
    """Round a quantity DOWN to the exchange's lot-size step."""
    import math
    if step <= 0:
        return qty
    n = math.floor(qty / step)
    decimals = max(0, -int(round(math.log10(step)))) if step < 1 else 0
    return round(n * step, decimals)


# ------------------------------- the bot ---------------------------------
class Bot:
    def __init__(self):
        self.mode = (cfg("BOT_MODE", "dryrun") or "dryrun").lower()
        self.symbol = cfg("SYMBOL", "BTCUSDT").upper()
        self.interval = cfg("INTERVAL", "1h")
        self.fast = int(cfg("FAST", "7"))
        self.slow = int(cfg("SLOW", "25"))
        self.quote_per_trade = float(cfg("QUOTE_PER_TRADE", "15"))
        self.poll_seconds = int(cfg("POLL_SECONDS", "60"))
        self.stop_loss_pct = float(cfg("STOP_LOSS_PCT", "0") or 0)
        self.state = load_state()
        self.client = None
        self.step_size = 0.0

        if self.fast >= self.slow:
            sys.exit("FAST must be smaller than SLOW.")

        if self.mode in ("testnet", "live"):
            self._connect()

    def _connect(self):
        try:
            from binance.client import Client
        except ImportError:
            sys.exit("Install dependencies first:  pip install -r bot/requirements.txt")
        key, secret = cfg("BINANCE_API_KEY"), cfg("BINANCE_API_SECRET")
        if not key or not secret:
            sys.exit("Set BINANCE_API_KEY and BINANCE_API_SECRET (see config.example.env).")
        self.client = Client(key, secret, testnet=(self.mode == "testnet"))
        # cache the lot-size step so SELL quantities are valid
        info = self.client.get_symbol_info(self.symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                self.step_size = float(f["stepSize"])
        log(f"Connected to Binance ({self.mode}). {self.symbol} lot step = {self.step_size}")

    # --- market data ---
    def closes(self):
        limit = self.slow + 2
        if self.mode == "dryrun":
            # dryrun still needs real prices: use the public REST endpoint
            import urllib.request
            url = (f"https://api.binance.com/api/v3/klines?symbol={self.symbol}"
                   f"&interval={self.interval}&limit={limit}")
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.load(r)
        else:
            data = self.client.get_klines(symbol=self.symbol, interval=self.interval, limit=limit)
        return [float(k[4]) for k in data]

    # --- orders ---
    def buy(self, price):
        qty = self.quote_per_trade / price
        if self.mode == "dryrun":
            log(f"DRYRUN 🟢 would BUY ~{qty:.6f} {self.symbol} for {self.quote_per_trade} quote @ ~{price:.4f}")
        else:
            order = self.client.order_market_buy(symbol=self.symbol, quoteOrderQty=self.quote_per_trade)
            qty = float(order.get("executedQty", qty))
            spent = float(order.get("cummulativeQuoteQty", self.quote_per_trade))
            price = spent / qty if qty else price
            log(f"{self.mode.upper()} 🟢 BOUGHT {qty:.6f} @ {price:.4f}")
        self.state.update(position="long", entry_price=price, base_qty=qty)
        save_state(self.state)
        record_trade("BUY", price, qty, self.mode)

    def sell(self, price, reason):
        qty = self.state["base_qty"]
        if self.mode == "dryrun":
            log(f"DRYRUN 🔴 would SELL {qty:.6f} {self.symbol} @ ~{price:.4f} ({reason})")
        else:
            qty = round_step(qty, self.step_size)
            order = self.client.order_market_sell(symbol=self.symbol, quantity=qty)
            got = float(order.get("cummulativeQuoteQty", price * qty))
            price = got / qty if qty else price
            log(f"{self.mode.upper()} 🔴 SOLD {qty:.6f} @ {price:.4f} ({reason})")
        entry = self.state["entry_price"]
        pnl = (price - entry) * qty
        log(f"   trade P/L ≈ {pnl:+.4f} quote ({(price/entry-1)*100:+.2f}%)")
        self.state.update(position=None, entry_price=0.0, base_qty=0.0)
        save_state(self.state)
        record_trade("SELL", price, qty, self.mode)

    # --- one decision cycle ---
    def step(self):
        closes = self.closes()
        if len(closes) < self.slow + 1:
            log("Not enough candles yet.")
            return
        price = closes[-1]
        fast_now, slow_now = sma(closes, self.fast), sma(closes, self.slow)
        fast_prev, slow_prev = sma(closes[:-1], self.fast), sma(closes[:-1], self.slow)
        cross_up = fast_prev <= slow_prev and fast_now > slow_now
        cross_down = fast_prev >= slow_prev and fast_now < slow_now

        pos = self.state["position"]
        trend = "↑" if fast_now > slow_now else "↓"
        log(f"{self.symbol} {price:.4f} | fast={fast_now:.2f} slow={slow_now:.2f} {trend} | pos={pos or 'flat'}")

        if pos is None:
            if cross_up:
                log("📈 Golden cross — opening a position.")
                self.buy(price)
        else:
            entry = self.state["entry_price"]
            if self.stop_loss_pct and price <= entry * (1 - self.stop_loss_pct / 100):
                self.sell(price, f"stop-loss {self.stop_loss_pct}%")
            elif cross_down:
                log("📉 Death cross — closing the position.")
                self.sell(price, "death cross")

    def run(self):
        log(f"Bot started — mode={self.mode}, symbol={self.symbol}, interval={self.interval}, "
            f"SMA {self.fast}/{self.slow}, {self.quote_per_trade} quote/trade, "
            f"stop-loss={self.stop_loss_pct or 'off'}")
        if self.mode == "live":
            log("⚠️  LIVE MODE — trading REAL money. Ctrl+C to stop.")
        once = "--once" in sys.argv
        while True:
            try:
                self.step()
            except Exception as e:  # keep the loop alive on transient errors
                log(f"error: {e}")
            if once:
                break
            time.sleep(self.poll_seconds)


if __name__ == "__main__":
    load_env()
    Bot().run()
