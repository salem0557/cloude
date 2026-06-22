"""Self-optimizer: every cycle it grid-searches strategy parameters against
recent market data and keeps the best-performing combination per symbol.

This is the "يتعلّم ويحدّث نفسه" part #1 — the bot re-tunes itself from the
latest price action instead of using fixed, stale settings.
"""

from __future__ import annotations

import itertools

from backtest import run_backtest
from strategy import DEFAULT_PARAMS

# Search grid. Kept modest so a full cycle finishes quickly for many symbols.
GRID = {
    "fast": [5, 7, 9, 12],
    "slow": [21, 25, 30, 50],
    "rsi_buy_max": [65, 70, 75],
    "stop_loss_pct": [3.0, 5.0, 8.0],
    "take_profit_pct": [8.0, 12.0, 20.0],
}


def _candidates():
    keys = list(GRID.keys())
    for combo in itertools.product(*(GRID[k] for k in keys)):
        params = dict(zip(keys, combo))
        if params["fast"] >= params["slow"]:
            continue
        yield params


def optimize_symbol(closes):
    """Find the best parameters for one symbol's recent ``closes``.

    Returns (best_params, best_metrics). Falls back to defaults if nothing
    beats a no-trade baseline.
    """
    best_params = dict(DEFAULT_PARAMS)
    best_metrics = {"score": -1000.0, "return_pct": 0.0, "trades": 0,
                    "win_rate": 0.0, "max_drawdown_pct": 0.0}

    for cand in _candidates():
        params = dict(DEFAULT_PARAMS)
        params.update(cand)
        metrics = run_backtest(closes, params)
        if metrics["score"] > best_metrics["score"]:
            best_metrics = metrics
            best_params = params

    return best_params, best_metrics
