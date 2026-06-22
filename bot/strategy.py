"""Trading strategy: SMA crossover + RSI filter, optionally confirmed by ML.

The same signal logic is used for both back-testing and live trading so that
what the optimizer measures is exactly what the bot will execute.

A *signal* for a single bar is one of: "buy", "sell", "hold".  Position
management (stop-loss / take-profit) is layered on top by the caller, since it
depends on the live entry price.
"""

from __future__ import annotations

from indicators import sma_series, rsi_series

# Default parameters. The optimizer overrides these per-symbol every cycle.
DEFAULT_PARAMS = {
    "fast": 7,
    "slow": 25,
    "rsi_period": 14,
    "rsi_buy_max": 70,    # don't buy if already overbought
    "rsi_sell_min": 30,   # don't panic-sell if already oversold
    "stop_loss_pct": 5.0,
    "take_profit_pct": 12.0,
    "ml_buy_threshold": 0.55,  # min ML "up" probability to allow a buy
}


def merge_params(params):
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update({k: v for k, v in params.items() if v is not None})
    return p


def crossover_signals(closes, params):
    """Return a list of raw signals ("buy"/"sell"/"hold") aligned to closes.

    "buy"  = fast SMA crosses above slow AND not overbought.
    "sell" = fast SMA crosses below slow AND not oversold.
    """
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


def latest_signal(closes, params):
    """The signal for the most recent (closed) bar."""
    sigs = crossover_signals(closes, params)
    return sigs[-1] if sigs else "hold"
