"""A simple long-only spot back-tester used by the self-optimizer.

It replays a price series bar-by-bar applying the same strategy signals the
live bot uses, including stop-loss and take-profit, and reports performance
metrics. Fees and slippage are modelled with a flat per-trade cost so the
optimizer doesn't fall in love with hyperactive, fee-bleeding settings.
"""

from __future__ import annotations

from strategy import crossover_signals, merge_params

FEE_PCT = 0.1  # round-trip-ish fee/slippage assumption per side (%)


def run_backtest(closes, params, fee_pct=FEE_PCT):
    """Return a metrics dict for ``params`` over ``closes``.

    Metrics: return_pct, trades, win_rate, max_drawdown_pct, score.
    """
    p = merge_params(params)
    signals = crossover_signals(closes, params)

    cash = 1.0          # start with 1 unit of quote currency
    qty = 0.0           # base held
    entry = 0.0
    trades = 0
    wins = 0
    equity_curve = []
    peak = 1.0
    max_dd = 0.0

    for i in range(len(closes)):
        price = closes[i]
        # mark-to-market equity
        equity = cash + qty * price
        equity_curve.append(equity)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

        if qty > 0:
            change = (price / entry - 1) * 100
            hit_sl = p["stop_loss_pct"] and change <= -p["stop_loss_pct"]
            hit_tp = p["take_profit_pct"] and change >= p["take_profit_pct"]
            if hit_sl or hit_tp or signals[i] == "sell":
                cash = qty * price * (1 - fee_pct / 100)
                if cash > entry * qty:
                    wins += 1
                qty = 0.0
                trades += 1
                entry = 0.0
                continue

        if qty == 0 and signals[i] == "buy":
            qty = (cash * (1 - fee_pct / 100)) / price
            entry = price
            cash = 0.0

    final_equity = cash + qty * closes[-1] if closes else 1.0
    return_pct = (final_equity - 1.0) * 100
    win_rate = (wins / trades * 100) if trades else 0.0

    # Score rewards return, penalises drawdown, and ignores no-trade settings.
    score = return_pct - 0.5 * max_dd
    if trades == 0:
        score = -999.0

    return {
        "return_pct": round(return_pct, 2),
        "trades": trades,
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_dd, 2),
        "score": round(score, 2),
    }
