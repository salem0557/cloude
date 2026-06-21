#!/usr/bin/env python3
"""Self-optimizing multi-coin crypto trading bot for Binance Spot.

What it does
------------
* Trades a basket of top coins (BTC, ETH, BNB, SOL, …) on the spot market.
* Every ``OPTIMIZE_HOURS`` (default 2) it RE-LEARNS:
    1. grid-searches strategy parameters on recent candles (back-testing) and
       keeps the best per coin  — optimizer.py
    2. retrains a small ML classifier per coin that confirms entries
       — ml_model.py
  then ranks coins by back-test score and trades only the strongest ``TOP_N``.
* Risk controls: per-trade size, max open positions, stop-loss, take-profit,
  and a daily-loss kill-switch.
* Writes a public status snapshot for the web dashboard (no keys exposed).

Modes (BOT_MODE), safest first:
  dryrun  (default) – simulates everything on real prices. Zero risk.
  testnet           – real orders, fake money (Binance Spot Testnet).
  live              – real orders, REAL money. You must opt in explicitly.

This is an educational tool, NOT financial advice. Bots lose money too. Start in
dryrun, graduate to testnet, and only ever risk what you can afford to lose.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, date
from pathlib import Path

from exchange import Exchange
from optimizer import optimize_symbol
from strategy import latest_signal, merge_params
import ml_model
import dashboard

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"
TRADES_CSV = HERE / "trades.csv"

DEFAULT_UNIVERSE = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT"


# ----------------------------- configuration -----------------------------
def load_env():
    env_path = HERE / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            # strip inline comments and whitespace
            os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())


def cfg(name, default=None):
    return os.environ.get(name, default)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "positions": {},        # symbol -> {entry_price, qty, opened}
        "params": {},           # symbol -> tuned params
        "scores": {},           # symbol -> backtest metrics
        "ml_acc": {},           # symbol -> ml accuracy
        "active": [],
        "last_optimize": None,
        "realized_pnl": 0.0,
        "equity": 0.0,
        "trades": [],           # recent trades for dashboard
        "day": str(date.today()),
        "day_start_realized": 0.0,
        "halted": False,
    }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def record_trade(state, side, symbol, price, qty, mode, reason=""):
    new = not TRADES_CSV.exists()
    with TRADES_CSV.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "mode", "symbol", "side", "price", "qty",
                        "quote_value", "reason"])
        w.writerow([now(), mode, symbol, side, f"{price:.8f}", f"{qty:.8f}",
                    f"{price * qty:.4f}", reason])
    state["trades"].append({
        "time": iso(), "symbol": symbol, "side": side,
        "price": round(price, 6), "qty": qty,
        "quote": round(price * qty, 2), "reason": reason,
    })
    state["trades"] = state["trades"][-50:]


# ------------------------------- the bot ---------------------------------
class Bot:
    def __init__(self):
        self.mode = (cfg("BOT_MODE", "dryrun") or "dryrun").lower()
        self.universe = [s.strip().upper()
                         for s in cfg("SYMBOLS", DEFAULT_UNIVERSE).split(",")
                         if s.strip()]
        self.interval = cfg("INTERVAL", "1h")
        self.quote_per_trade = float(cfg("QUOTE_PER_TRADE", "15"))
        self.poll_seconds = int(cfg("POLL_SECONDS", "60"))
        self.optimize_hours = float(cfg("OPTIMIZE_HOURS", "2"))
        self.top_n = int(cfg("TOP_N", "3"))
        self.history = int(cfg("HISTORY", "500"))
        self.max_open = int(cfg("MAX_OPEN_POSITIONS", "3"))
        self.daily_loss_limit = float(cfg("DAILY_LOSS_LIMIT", "0") or 0)
        self.start_equity = float(cfg("PAPER_EQUITY", "1000"))

        self.state = load_state()
        self.ex = Exchange(self.mode, cfg("BINANCE_API_KEY"),
                           cfg("BINANCE_API_SECRET"))
        self._last_opt_ts = 0.0
        if not self.state.get("equity"):
            self.state["equity"] = self.start_equity

        if self.mode == "live":
            confirm = (cfg("CONFIRM_LIVE", "") or "").upper()
            if confirm != "I_UNDERSTAND_THE_RISK":
                raise SystemExit(
                    "LIVE mode refused. To trade REAL money set "
                    "CONFIRM_LIVE=I_UNDERSTAND_THE_RISK in your .env.")

    # ---- the learning / self-update step (runs every OPTIMIZE_HOURS) ----
    def self_update(self):
        log("🧠 Self-update: back-testing + retraining ML on latest data…")
        scored = []
        for symbol in self.universe:
            try:
                closes = self.ex.closes(symbol, self.interval, self.history)
            except Exception as e:
                log(f"   {symbol}: data error {e}")
                continue
            if len(closes) < 80:
                continue
            params, metrics = optimize_symbol(closes)
            acc = ml_model.train(symbol, closes)
            self.state["params"][symbol] = params
            self.state["scores"][symbol] = metrics
            self.state["ml_acc"][symbol] = acc
            scored.append((symbol, metrics["score"]))
            log(f"   {symbol}: score={metrics['score']} "
                f"ret={metrics['return_pct']}% win={metrics['win_rate']}% "
                f"fast={params['fast']} slow={params['slow']} "
                f"ml_acc={acc}")

        scored.sort(key=lambda x: x[1], reverse=True)
        # only trade coins whose recent strategy was actually profitable
        ranked = [s for s, sc in scored if sc > 0][: self.top_n]
        # always keep symbols we currently hold so we can manage/exit them
        for held in self.state["positions"]:
            if held not in ranked:
                ranked.append(held)
        self.state["active"] = ranked
        self.state["last_optimize"] = iso()
        save_state(self.state)
        log(f"✅ Self-update done. Trading: {ranked or '(none profitable)'}")

    # ------------------------------ trading ------------------------------
    def open_position(self, symbol, price):
        if len(self.state["positions"]) >= self.max_open:
            return
        fill, qty = self.ex.buy(symbol, self.quote_per_trade, price)
        self.state["positions"][symbol] = {
            "entry_price": fill, "qty": qty, "opened": iso()}
        if self.mode == "dryrun":
            self.state["equity"] -= fill * qty
        record_trade(self.state, "BUY", symbol, fill, qty, self.mode, "signal")
        log(f"🟢 BUY {symbol} {qty:.6f} @ {fill:.4f}")

    def close_position(self, symbol, price, reason):
        pos = self.state["positions"].get(symbol)
        if not pos:
            return
        fill, qty = self.ex.sell(symbol, pos["qty"], price)
        pnl = (fill - pos["entry_price"]) * qty
        self.state["realized_pnl"] += pnl
        if self.mode == "dryrun":
            self.state["equity"] += fill * qty
        record_trade(self.state, "SELL", symbol, fill, qty, self.mode, reason)
        pct = (fill / pos["entry_price"] - 1) * 100 if pos["entry_price"] else 0
        log(f"🔴 SELL {symbol} {qty:.6f} @ {fill:.4f} ({reason}) "
            f"P/L {pnl:+.2f} ({pct:+.2f}%)")
        del self.state["positions"][symbol]

    def manage_symbol(self, symbol, prices):
        params = merge_params(self.state["params"].get(symbol))
        closes = self.ex.closes(symbol, self.interval, self.history)
        price = closes[-1]
        prices[symbol] = price
        signal = latest_signal(closes, params)
        ml_prob = ml_model.predict_up(symbol, closes)

        pos = self.state["positions"].get(symbol)
        if pos:
            entry = pos["entry_price"]
            change = (price / entry - 1) * 100 if entry else 0
            if params["stop_loss_pct"] and change <= -params["stop_loss_pct"]:
                self.close_position(symbol, price, f"stop-loss {change:.1f}%")
            elif params["take_profit_pct"] and change >= params["take_profit_pct"]:
                self.close_position(symbol, price, f"take-profit {change:.1f}%")
            elif signal == "sell":
                self.close_position(symbol, price, "death cross")
        else:
            ml_ok = (ml_prob is None) or (ml_prob >= params["ml_buy_threshold"])
            if signal == "buy" and ml_ok:
                self.open_position(symbol, price)
            elif signal == "buy" and not ml_ok:
                log(f"⏸️  {symbol} buy signal skipped (ML {ml_prob} < "
                    f"{params['ml_buy_threshold']})")

    # --------------------------- risk / kill ---------------------------
    def check_daily_limit(self):
        today = str(date.today())
        if self.state.get("day") != today:
            self.state["day"] = today
            self.state["day_start_realized"] = self.state["realized_pnl"]
            self.state["halted"] = False
        if self.daily_loss_limit <= 0:
            return
        day_pnl = self.state["realized_pnl"] - self.state["day_start_realized"]
        if day_pnl <= -abs(self.daily_loss_limit) and not self.state["halted"]:
            self.state["halted"] = True
            log(f"🛑 Daily loss limit hit ({day_pnl:+.2f}). "
                f"Closing positions, pausing new entries until tomorrow.")

    # ------------------------------ cycle ------------------------------
    def step(self):
        self.check_daily_limit()
        need_opt = (time.time() - self._last_opt_ts) >= self.optimize_hours * 3600
        if need_opt or not self.state.get("active"):
            self.self_update()
            self._last_opt_ts = time.time()

        prices = {}
        for symbol in list(self.state["active"]):
            try:
                if self.state.get("halted"):
                    # only allow exits while halted
                    if symbol in self.state["positions"]:
                        closes = self.ex.closes(symbol, self.interval, self.history)
                        prices[symbol] = closes[-1]
                        self.close_position(symbol, closes[-1], "daily halt")
                    continue
                self.manage_symbol(symbol, prices)
            except Exception as e:
                log(f"   {symbol}: error {e}")

        save_state(self.state)
        try:
            dashboard.write_snapshot(
                self.mode, self.universe, self.state["active"],
                self.state["params"], self.state["positions"],
                self.state["scores"], self.state["ml_acc"],
                self.state["trades"], self.state["equity"],
                self.state["realized_pnl"], self.state["last_optimize"], prices)
        except Exception as e:
            log(f"dashboard write error: {e}")

    def run(self):
        log(f"Bot started — mode={self.mode}, universe={self.universe}, "
            f"interval={self.interval}, TOP_N={self.top_n}, "
            f"{self.quote_per_trade} quote/trade, "
            f"self-update every {self.optimize_hours}h")
        if self.mode == "live":
            log("⚠️  LIVE MODE — trading REAL money. Ctrl+C to stop.")
        once = "--once" in sys.argv
        while True:
            try:
                self.step()
            except Exception as e:
                log(f"cycle error: {e}")
            if once:
                break
            time.sleep(self.poll_seconds)


if __name__ == "__main__":
    load_env()
    Bot().run()
