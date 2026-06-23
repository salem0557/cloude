"""Trading strategies — a competing BASKET the optimizer chooses from.

Instead of one hard-coded strategy, the bot carries a library of well-known
strategies and the walk-forward optimizer picks the best (strategy + parameters)
PER COIN, out-of-sample, every cycle. So a trending coin may trade on Supertrend-
style EMA momentum while a ranging coin trades Bollinger mean-reversion — each
coin gets the approach that actually has an edge on it right now.

All strategies operate on the close series only, so they plug straight into the
existing closes-only back-tester/optimizer with no extra data plumbing.

A *signal* per bar is "buy", "sell" or "hold". Position management (stop-loss /
take-profit / trailing) is layered on top by the caller from the live entry price.

Selection is controlled by the STRATEGY env var:
  auto (default)  the optimizer competes ALL strategies and picks the best/coin
  <name>          force a single strategy (e.g. scalp, bollinger, macd, …)
"""

from __future__ import annotations

import os

from indicators import sma_series, ema_series, rsi_series

# Default parameters. The optimizer overrides the relevant subset per-symbol.
DEFAULT_PARAMS = {
    # shared exits
    "stop_loss_pct": 5.0,
    "take_profit_pct": 12.0,
    "ml_buy_threshold": 0.55,
    # crossover / scalp
    "fast": 7,
    "slow": 25,
    "rsi_period": 14,
    "rsi_buy_max": 70,
    "rsi_sell_min": 30,
    "rsi_dip": 40,
    "rsi_overbought": 72,
    # bollinger / z-score
    "bb_period": 20,
    "bb_std": 2.0,
    "z_period": 20,
    "z_buy": -2.0,
    # macd
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # donchian
    "donchian_n": 20,
    # ema ribbon
    "ema_fast": 8,
    "ema_mid": 21,
    "ema_slow": 55,
    # rsi mean-reversion
    "rsi_os": 30,
    "rsi_ob": 70,
    # stochastic
    "stoch_n": 14,
    "stoch_buy": 20,
    "stoch_sell": 80,
}


def strategy_mode():
    """Active strategy selector. 'auto' = let the optimizer compete them all."""
    return (os.environ.get("STRATEGY", "auto") or "auto").lower()


def use_scalp():
    """True only when scalp is FORCED (kept for the auto-revert safety check)."""
    return strategy_mode() == "scalp"


def merge_params(params):
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update({k: v for k, v in params.items() if v is not None})
    return p


# ----------------------------- helpers -----------------------------
def _rolling_std(values, n):
    out = [None] * len(values)
    n = int(n)
    if n <= 1:
        return out
    for i in range(n - 1, len(values)):
        w = values[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return out


def _macd_lines(closes, fast, slow, signal):
    ef = ema_series(closes, int(fast))
    es = ema_series(closes, int(slow))
    macd = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            macd[i] = ef[i] - es[i]
    sig = [None] * len(closes)
    start = next((i for i, v in enumerate(macd) if v is not None), None)
    signal = int(signal)
    if start is not None and len(closes) - start >= signal and signal > 0:
        k = 2 / (signal + 1)
        prev = sum(macd[start:start + signal]) / signal
        sig[start + signal - 1] = prev
        for i in range(start + signal, len(closes)):
            prev = macd[i] * k + prev * (1 - k)
            sig[i] = prev
    return macd, sig


# ----------------------------- strategies -----------------------------
def crossover_signals(closes, params):
    """SMA fast/slow crossover with an RSI overbought filter (trend following)."""
    p = merge_params(params)
    fast = sma_series(closes, int(p["fast"]))
    slow = sma_series(closes, int(p["slow"]))
    r = rsi_series(closes, int(p["rsi_period"]))
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
            continue
        cross_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
        cross_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
        rsi_now = r[i] if r[i] is not None else 50.0
        if cross_up and rsi_now <= p["rsi_buy_max"]:
            out[i] = "buy"
        elif cross_down and rsi_now >= p["rsi_sell_min"]:
            out[i] = "sell"
    return out


def scalp_signals(closes, params):
    """Buy-the-dip in an uptrend: fast>slow SMA and RSI rebounding off a dip."""
    p = merge_params(params)
    fast = sma_series(closes, int(p["fast"]))
    slow = sma_series(closes, int(p["slow"]))
    r = rsi_series(closes, int(p["rsi_period"]))
    dip, ob = p["rsi_dip"], p["rsi_overbought"]
    out = ["hold"] * len(closes)
    for i in range(2, len(closes)):
        if None in (fast[i], slow[i], r[i], r[i - 1]):
            continue
        uptrend = fast[i] > slow[i]
        momentum_up = r[i] > r[i - 1]
        if uptrend and momentum_up and dip <= r[i] < ob:
            out[i] = "buy"
        elif (not uptrend) or r[i] >= ob:
            out[i] = "sell"
    return out


def bollinger_signals(closes, params):
    """Mean reversion: buy at the lower band, exit back at the middle band."""
    p = merge_params(params)
    n = int(p["bb_period"])
    k = float(p["bb_std"])
    mid = sma_series(closes, n)
    sd = _rolling_std(closes, n)
    out = ["hold"] * len(closes)
    for i in range(len(closes)):
        if mid[i] is None or sd[i] is None:
            continue
        lower = mid[i] - k * sd[i]
        if closes[i] <= lower:
            out[i] = "buy"
        elif closes[i] >= mid[i]:
            out[i] = "sell"
    return out


def bollinger_breakout_signals(closes, params):
    """Momentum: buy a close breaking above the upper band, exit below middle."""
    p = merge_params(params)
    n = int(p["bb_period"])
    k = float(p["bb_std"])
    mid = sma_series(closes, n)
    sd = _rolling_std(closes, n)
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if None in (mid[i], sd[i], mid[i - 1], sd[i - 1]):
            continue
        upper = mid[i] + k * sd[i]
        upper_prev = mid[i - 1] + k * sd[i - 1]
        if closes[i] > upper and closes[i - 1] <= upper_prev:
            out[i] = "buy"
        elif closes[i] < mid[i]:
            out[i] = "sell"
    return out


def macd_signals(closes, params):
    """MACD line crossing its signal line (momentum)."""
    p = merge_params(params)
    macd, sig = _macd_lines(closes, p["macd_fast"], p["macd_slow"],
                            p["macd_signal"])
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if None in (macd[i], sig[i], macd[i - 1], sig[i - 1]):
            continue
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i]:
            out[i] = "buy"
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i]:
            out[i] = "sell"
    return out


def rsi_meanrev_signals(closes, params):
    """Classic RSI mean reversion: buy oversold turning up, sell overbought."""
    p = merge_params(params)
    r = rsi_series(closes, int(p["rsi_period"]))
    os_, ob = p["rsi_os"], p["rsi_ob"]
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if r[i] is None or r[i - 1] is None:
            continue
        if r[i] < os_ and r[i] > r[i - 1]:
            out[i] = "buy"
        elif r[i] > ob:
            out[i] = "sell"
    return out


def donchian_signals(closes, params):
    """Donchian breakout on closes: buy above the prior n-bar high, sell below
    the prior n-bar low (turtle-style trend following)."""
    p = merge_params(params)
    n = int(p["donchian_n"])
    out = ["hold"] * len(closes)
    for i in range(n, len(closes)):
        window = closes[i - n:i]
        hh, ll = max(window), min(window)
        if closes[i] > hh:
            out[i] = "buy"
        elif closes[i] < ll:
            out[i] = "sell"
    return out


def ema_ribbon_signals(closes, params):
    """Triple-EMA trend: buy when fast>mid>slow aligns bullish, exit when fast
    drops back below mid (a Supertrend-like, close-only momentum filter)."""
    p = merge_params(params)
    ef = ema_series(closes, int(p["ema_fast"]))
    em = ema_series(closes, int(p["ema_mid"]))
    es = ema_series(closes, int(p["ema_slow"]))
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if None in (ef[i], em[i], es[i], ef[i - 1], em[i - 1], es[i - 1]):
            continue
        aligned = ef[i] > em[i] > es[i]
        aligned_prev = ef[i - 1] > em[i - 1] > es[i - 1]
        if aligned and not aligned_prev:
            out[i] = "buy"
        elif ef[i] < em[i]:
            out[i] = "sell"
    return out


def stochastic_signals(closes, params):
    """Stochastic oscillator (on closes): buy crossing up out of oversold, sell
    crossing down out of overbought."""
    p = merge_params(params)
    n = int(p["stoch_n"])
    buy, sell = p["stoch_buy"], p["stoch_sell"]
    kline = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        lo, hi = min(w), max(w)
        kline[i] = (closes[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    out = ["hold"] * len(closes)
    for i in range(1, len(closes)):
        if kline[i] is None or kline[i - 1] is None:
            continue
        if kline[i - 1] <= buy and kline[i] > buy:
            out[i] = "buy"
        elif kline[i - 1] >= sell and kline[i] < sell:
            out[i] = "sell"
    return out


def zscore_signals(closes, params):
    """Z-score mean reversion: buy when price is z_buy std below its mean, exit
    when it returns to the mean (VWAP-style reversion proxy)."""
    p = merge_params(params)
    n = int(p["z_period"])
    z_buy = float(p["z_buy"])
    mid = sma_series(closes, n)
    sd = _rolling_std(closes, n)
    out = ["hold"] * len(closes)
    for i in range(len(closes)):
        if mid[i] is None or sd[i] is None or sd[i] == 0:
            continue
        z = (closes[i] - mid[i]) / sd[i]
        if z <= z_buy:
            out[i] = "buy"
        elif z >= 0:
            out[i] = "sell"
    return out


# name -> (signal function, optimizer grid). Grids kept compact so competing all
# strategies across the shortlist stays fast. Shared exits live in each grid.
_SL = [1.5, 3.0]
_TP = [2.5, 5.0]
STRATEGIES = {
    "crossover": (crossover_signals, {
        "fast": [5, 9], "slow": [21, 50],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "scalp": (scalp_signals, {
        "fast": [3, 5], "slow": [13, 21], "rsi_dip": [40],
        "stop_loss_pct": [1.0, 2.0], "take_profit_pct": [1.5, 3.0]}),
    "bollinger": (bollinger_signals, {
        "bb_period": [20], "bb_std": [2.0, 2.5],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "bollinger_breakout": (bollinger_breakout_signals, {
        "bb_period": [20], "bb_std": [2.0, 2.5],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "macd": (macd_signals, {
        "macd_fast": [12], "macd_slow": [26], "macd_signal": [9],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "rsi_meanrev": (rsi_meanrev_signals, {
        "rsi_os": [25, 30], "rsi_ob": [70, 75],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "donchian": (donchian_signals, {
        "donchian_n": [20, 30],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "ema_ribbon": (ema_ribbon_signals, {
        "ema_fast": [8], "ema_mid": [21], "ema_slow": [55],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "stochastic": (stochastic_signals, {
        "stoch_n": [14], "stoch_buy": [20], "stoch_sell": [80],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
    "zscore": (zscore_signals, {
        "z_period": [20], "z_buy": [-2.0, -2.5],
        "stop_loss_pct": _SL, "take_profit_pct": _TP}),
}

_SIGNALS = {name: fn for name, (fn, _grid) in STRATEGIES.items()}


def signals(closes, params):
    """Dispatch to the strategy named in params['strategy'], else to the forced
    STRATEGY mode, else to crossover (a calm default for no-edge coins)."""
    p = merge_params(params)
    fn = _SIGNALS.get(p.get("strategy"))
    if fn is None:
        fn = _SIGNALS.get(strategy_mode(), crossover_signals)
    return fn(closes, p)


def latest_signal(closes, params):
    """The signal for the most recent (closed) bar."""
    sigs = signals(closes, params)
    return sigs[-1] if sigs else "hold"
