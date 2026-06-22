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

from exchange import Exchange, usdt_universe
from optimizer import optimize_symbol
from strategy import latest_signal, merge_params, DEFAULT_PARAMS
from backtest import run_backtest
import ml_model
import best_practices
import publish
import monitor
import dashboard

HERE = Path(__file__).resolve().parent
# DATA_DIR lets a cloud host keep state on a persistent volume across redeploys.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(HERE)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
TRADES_CSV = DATA_DIR / "trades.csv"

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
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    monitor.add_log(line)


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
        self.fixed_universe = [s.strip().upper()
                               for s in cfg("SYMBOLS", DEFAULT_UNIVERSE).split(",")
                               if s.strip()]
        # AUTO_UNIVERSE: scan ALL tradable USDT pairs (by liquidity) instead of
        # a fixed basket, then deep-optimize only a rolling shortlist.
        self.auto_universe = (cfg("AUTO_UNIVERSE", "") or "").lower() \
            in ("1", "true", "yes", "on")
        self.min_quote_volume = float(cfg("MIN_QUOTE_VOLUME", "5000000"))
        self.max_universe = int(cfg("MAX_UNIVERSE", "250"))
        self.scan_batch = int(cfg("SCAN_BATCH", "30"))
        self.shortlist_n = int(cfg("SHORTLIST", "12"))
        self._scan_cursor = 0
        self._last_universe_ts = 0.0
        self.universe = list(self.fixed_universe)
        self.interval = cfg("INTERVAL", "1h")
        self.quote_per_trade = float(cfg("QUOTE_PER_TRADE", "15"))
        self.poll_seconds = int(cfg("POLL_SECONDS", "30"))
        # Real-time learning: re-tune parameters EVERY cycle. Set to false to
        # fall back to the slower OPTIMIZE_HOURS schedule.
        self.realtime = (cfg("REALTIME_LEARNING", "true") or "").lower() \
            in ("1", "true", "yes", "on")
        self.optimize_hours = float(cfg("OPTIMIZE_HOURS", "2"))
        # ML training is heavier than the grid-search, so it has its own
        # (still frequent) cadence. 0 = retrain every cycle too.
        self.ml_retrain_min = float(cfg("ML_RETRAIN_MINUTES", "10"))
        self.top_n = int(cfg("TOP_N", "3"))
        self.history = int(cfg("HISTORY", "500"))
        self.max_open = int(cfg("MAX_OPEN_POSITIONS", "3"))
        self.daily_loss_limit = float(cfg("DAILY_LOSS_LIMIT", "0") or 0)
        # Trailing stop: ride the rise, sell when price pulls back this % from
        # its peak. 0 = off (use the fixed take-profit instead).
        self.trailing_pct = float(cfg("TRAILING_STOP_PCT", "0") or 0)
        self.start_equity = float(cfg("PAPER_EQUITY", "1000"))

        # Publishing / durable state backup config (read early so we can
        # restore state from GitHub before loading it on a stateless host).
        self.publish_on = (cfg("PUBLISH_DASHBOARD", "") or "").lower() \
            in ("1", "true", "yes", "on")
        self.gh_repo = cfg("GH_REPO", "salem0557/cloude")
        self.gh_token = cfg("GITHUB_TOKEN")
        self.pub_branch = cfg("PUBLISH_BRANCH", "bot-live")
        self.pub_seconds = int(cfg("PUBLISH_SECONDS", "60"))

        # On a stateless cloud host, restore state.json from GitHub if absent.
        if not STATE_FILE.exists() and self.publish_on and self.gh_token:
            if publish.restore_state(self.gh_repo, self.pub_branch,
                                     self.gh_token, STATE_FILE):
                log("♻️  restored state from GitHub backup")

        self.state = load_state()
        self.ex = Exchange(self.mode, cfg("BINANCE_API_KEY"),
                           cfg("BINANCE_API_SECRET"))
        self._last_opt_ts = 0.0
        self._last_ml_ts = 0.0
        self._last_pub_ts = 0.0
        self._last_bal_ts = 0.0
        self.account = None      # real Binance balance (live/testnet)
        self.regime = {"allow_buys": True, "risk_multiplier": 1.0,
                       "reason": "—"}
        self.state.setdefault("scan_scores", {})
        self.candidates = list(self.fixed_universe)
        self.refresh_universe()

        if not self.state.get("equity"):
            self.state["equity"] = self.start_equity

        if self.mode == "live":
            confirm = (cfg("CONFIRM_LIVE", "") or "").upper()
            if confirm != "I_UNDERSTAND_THE_RISK":
                raise SystemExit(
                    "LIVE mode refused. To trade REAL money set "
                    "CONFIRM_LIVE=I_UNDERSTAND_THE_RISK in your .env.")

    # ---- the learning / self-update step ----
    # ----------------------- universe / scanning -----------------------
    def refresh_universe(self):
        """Build the trading universe (auto = all liquid USDT pairs)."""
        if not self.auto_universe:
            self.universe = list(self.fixed_universe)
            return
        try:
            uni = usdt_universe(self.min_quote_volume, self.max_universe)
            if uni:
                self.universe = uni
                self._last_universe_ts = time.time()
                log(f"🌐 Auto-universe: scanning {len(uni)} USDT pairs "
                    f"(top by 24h volume)")
        except Exception as e:
            log(f"universe build error: {e}")
            if not self.universe:
                self.universe = list(self.fixed_universe)

    def _scan_pass(self):
        """Quick-score the next batch of the universe (rotating) and keep a
        rolling map of each coin's recent back-test score with default params."""
        if not self.universe:
            return
        n = len(self.universe)
        batch = [self.universe[(self._scan_cursor + i) % n]
                 for i in range(min(self.scan_batch, n))]
        self._scan_cursor = (self._scan_cursor + len(batch)) % n
        for symbol in batch:
            try:
                closes = self.ex.closes(symbol, self.interval,
                                        min(self.history, 200))
                if len(closes) >= 60:
                    self.state["scan_scores"][symbol] = \
                        run_backtest(closes, DEFAULT_PARAMS)["score"]
            except Exception:
                self.state["scan_scores"].pop(symbol, None)

    def _shortlist(self):
        """Best-scoring scanned coins (plus anything we currently hold)."""
        scanned = sorted(self.state["scan_scores"].items(),
                         key=lambda x: x[1], reverse=True)
        short = [s for s, sc in scanned][: self.shortlist_n]
        for held in self.state["positions"]:
            if held not in short:
                short.append(held)
        return short

    def self_update(self, retrain_ml):
        tag = "back-testing + retraining ML" if retrain_ml else "back-testing"
        if self.auto_universe:
            if (time.time() - self._last_universe_ts) >= 24 * 3600:
                self.refresh_universe()
            self._scan_pass()
            candidates = self._shortlist()
        else:
            candidates = list(self.universe)
        self.candidates = candidates
        log(f"🧠 Self-update ({tag}) — {len(candidates)} candidates"
            + (f" from {len(self.universe)} scanned" if self.auto_universe else ""))

        scored = []
        for symbol in candidates:
            try:
                closes = self.ex.closes(symbol, self.interval, self.history)
            except Exception as e:
                log(f"   {symbol}: data error {e}")
                continue
            if len(closes) < 80:
                continue
            params, metrics = optimize_symbol(closes)
            self.state["params"][symbol] = params
            self.state["scores"][symbol] = metrics
            if retrain_ml:
                self.state["ml_acc"][symbol] = ml_model.train(symbol, closes)
            acc = self.state["ml_acc"].get(symbol)
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
        # keep per-symbol maps from growing without bound over the rotation
        keep = set(candidates) | set(self.state["positions"])
        for d in (self.state["params"], self.state["scores"],
                  self.state["ml_acc"]):
            for k in [k for k in d if k not in keep]:
                d.pop(k, None)
        save_state(self.state)
        log(f"✅ Self-update done. Trading: {ranked or '(none profitable)'}")

    # ------------------------------ trading ------------------------------
    def open_position(self, symbol, price):
        if len(self.state["positions"]) >= self.max_open:
            return
        quote = self.quote_per_trade * self.regime.get("risk_multiplier", 1.0)
        fill, qty = self.ex.buy(symbol, quote, price)
        self.state["positions"][symbol] = {
            "entry_price": fill, "qty": qty, "opened": iso(), "peak": fill}
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
            pos["peak"] = max(pos.get("peak", entry), price)   # track high
            change = (price / entry - 1) * 100 if entry else 0
            reason = None
            if params["stop_loss_pct"] and change <= -params["stop_loss_pct"]:
                reason = f"stop-loss {change:.1f}%"
            elif self.trailing_pct and pos["peak"] > entry and \
                    price <= pos["peak"] * (1 - self.trailing_pct / 100):
                drop = (price / pos["peak"] - 1) * 100
                reason = f"trailing stop ({drop:.1f}% from peak, P/L {change:+.1f}%)"
            elif not self.trailing_pct and params["take_profit_pct"] \
                    and change >= params["take_profit_pct"]:
                reason = f"take-profit {change:.1f}%"
            elif signal == "sell":
                reason = "trend exit"
            if reason:
                self.close_position(symbol, price, reason)
        else:
            ml_ok = (ml_prob is None) or (ml_prob >= params["ml_buy_threshold"])
            regime_ok = self.regime.get("allow_buys", True)
            if signal == "buy" and ml_ok and regime_ok:
                self.open_position(symbol, price)
            elif signal == "buy" and not regime_ok:
                log(f"⏸️  {symbol} buy skipped — best-practices: "
                    f"{self.regime.get('reason')}")
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

        # Refresh the real Binance balance periodically (live/testnet) and use
        # it as the displayed equity so the dashboard shows true wallet value.
        if (time.time() - self._last_bal_ts) >= 60:
            try:
                summ = self.ex.account_summary()
            except Exception as e:
                summ = None
                if self.mode in ("live", "testnet"):
                    log(f"⚠️  balance read error: {e} — usually a missing "
                        "'Reading' permission or an IP restriction on the API key")
            if summ:
                self.account = summ
                self.state["equity"] = summ["total_usdt"]
                log(f"💰 balance: {summ['total_usdt']} USDT total, "
                    f"{summ['free_usdt']} USDT free")
            self._last_bal_ts = time.time()

        # Refresh the live "best-practices" market regime every cycle.
        try:
            self.regime = best_practices.get_regime()
            self.state["regime"] = self.regime
        except Exception as e:
            log(f"regime error: {e}")

        # Real-time learning: re-tune parameters every cycle (or on the
        # OPTIMIZE_HOURS schedule when realtime is off). Retrain the heavier
        # ML model on its own ML_RETRAIN_MINUTES cadence.
        now_ts = time.time()
        need_opt = self.realtime or not self.state.get("active") or \
            (now_ts - self._last_opt_ts) >= self.optimize_hours * 3600
        retrain_ml = (now_ts - self._last_ml_ts) >= self.ml_retrain_min * 60
        if need_opt:
            self.self_update(retrain_ml)
            self._last_opt_ts = now_ts
            if retrain_ml:
                self._last_ml_ts = now_ts

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
                self.mode, self.candidates, self.state["active"],
                self.state["params"], self.state["positions"],
                self.state["scores"], self.state["ml_acc"],
                self.state["trades"], self.state["equity"],
                self.state["realized_pnl"], self.state["last_optimize"], prices,
                regime=self.regime, account=self.account,
                learning={"realtime": self.realtime,
                          "poll_seconds": self.poll_seconds,
                          "ml_retrain_min": self.ml_retrain_min})
        except Exception as e:
            log(f"dashboard write error: {e}")

        # optionally push the snapshot + state backup to GitHub (so the website
        # shows live data and a stateless host keeps its positions)
        if self.publish_on and self.gh_token and \
                (time.time() - self._last_pub_ts) >= self.pub_seconds:
            ok = publish.publish(self.gh_repo, self.pub_branch, self.gh_token)
            publish.backup_state(self.gh_repo, self.pub_branch, self.gh_token,
                                 STATE_FILE)
            self._last_pub_ts = time.time()
            if not ok:
                log("⚠️  dashboard publish failed (check GITHUB_TOKEN / GH_REPO)")

    def run(self):
        # Start the web monitor if a PORT is provided (cloud hosts set $PORT).
        port = cfg("PORT")
        if port:
            try:
                monitor.start(port)
                log(f"📊 Web monitor on port {port}")
            except Exception as e:
                log(f"monitor start error: {e}")

        learn = "real-time (every cycle)" if self.realtime \
            else f"every {self.optimize_hours}h"
        uni = (f"{len(self.universe)} pairs (auto)" if self.auto_universe
               else str(self.universe))
        log(f"Bot started — mode={self.mode}, universe={uni}, "
            f"interval={self.interval}, TOP_N={self.top_n}, "
            f"{self.quote_per_trade} quote/trade, learning={learn}, "
            f"poll={self.poll_seconds}s, ML retrain every {self.ml_retrain_min}m")
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
