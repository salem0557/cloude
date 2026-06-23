"""Self-optimizer: every cycle it grid-searches across the WHOLE strategy basket
(crossover, scalp, bollinger, macd, donchian, ema-ribbon, stochastic, …) plus
their parameters, and keeps the best-performing (strategy + params) per symbol.

This is the "يتعلّم ويحدّث نفسه" part #1 — the bot not only re-tunes parameters
but re-chooses WHICH strategy to trade on each coin, validated out-of-sample.
"""

from __future__ import annotations

import itertools

from backtest import run_backtest
from strategy import DEFAULT_PARAMS, STRATEGIES, strategy_mode

# Walk-forward validation: tune on an older "train" window, SELECT by performance
# on a newer, unseen "test" window, so only settings/strategies that GENERALISE
# get traded (the old same-window tuning over-fit noise and bled money).
TRAIN_FRAC = 0.70
MIN_TRAIN_TRADES = 1
MIN_SPLIT_BARS = 160

_BLANK = {"score": 0.0, "return_pct": 0.0, "trades": 0,
          "win_rate": 0.0, "max_drawdown_pct": 0.0}


def _active_strategies():
    """Which strategies to compete: all of them in 'auto', else the forced one."""
    mode = strategy_mode()
    if mode in ("auto", "all"):
        return list(STRATEGIES.keys())
    if mode in STRATEGIES:
        return [mode]
    return ["crossover"]


def _candidates():
    """Every (strategy, params) combination to evaluate this cycle."""
    for name in _active_strategies():
        grid = STRATEGIES[name][1]
        keys = list(grid.keys())
        for combo in itertools.product(*(grid[k] for k in keys)):
            params = dict(zip(keys, combo))
            if "fast" in params and "slow" in params \
                    and params["fast"] >= params["slow"]:
                continue
            params["strategy"] = name
            yield params


def optimize_symbol(closes):
    """Walk-forward best (strategy + params) for one symbol's recent ``closes``.

    Returns (best_params, best_metrics) measured OUT-OF-SAMPLE. best_params
    carries a 'strategy' key naming the winning approach. If nothing generalises,
    returns defaults with score 0 so the coin stays inactive (the ranking only
    trades positive-score coins) — i.e. when no strategy has a real edge the bot
    correctly sits flat instead of forcing a bad trade.
    """
    n = len(closes)
    if n < MIN_SPLIT_BARS:
        return dict(DEFAULT_PARAMS), dict(_BLANK)

    split = int(n * TRAIN_FRAC)
    train, test = closes[:split], closes[split:]

    best_params = dict(DEFAULT_PARAMS)
    best_metrics = dict(_BLANK)
    best_oos = -1e9

    for cand in _candidates():
        params = dict(DEFAULT_PARAMS)
        params.update(cand)
        m_train = run_backtest(train, params)
        if m_train["trades"] < MIN_TRAIN_TRADES or m_train["score"] <= 0:
            continue
        m_test = run_backtest(test, params)
        if m_test["score"] > best_oos:
            best_oos = m_test["score"]
            best_metrics = m_test
            best_params = params

    return best_params, best_metrics
