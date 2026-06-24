"""A simple long-only spot back-tester used by the self-optimizer.

It replays a price series bar-by-bar applying the same strategy signals the
live bot uses, including stop-loss and take-profit, and reports performance
metrics. Fees and slippage are modelled with a flat per-trade cost so the
optimizer doesn't fall in love with hyperactive, fee-bleeding settings.
"""

from __future__ import annotations

from strategy import signals as strategy_signals, merge_params

# Per-SIDE cost: real Binance taker fee (~0.1%) PLUS spread + slippage on small
# alts. 0.1% was too optimistic and made the optimizer fall in love with
# hyperactive scalps whose tiny edge vanishes once real costs hit. 0.25%/side
# (~0.5% round-trip) is a realistic floor and keeps it honest.
FEE_PCT = 0.25
# Below this many trades a window's result is thin/noisy, so its score is
# gently penalised (a nudge, not a hammer — low-frequency trend trades are
# legitimate). The walk-forward train/test split is the real over-fit defence.
MIN_TRADES = 3


def run_backtest(closes, params, fee_pct=FEE_PCT):
    """Return a metrics dict for ``params`` over ``closes``.

    Metrics: return_pct, trades, win_rate, max_drawdown_pct, score.
    """
    p = merge_params(params)
    signals = strategy_signals(closes, params)

    cash = 1.0          # start with 1 unit of quote currency
    qty = 0.0           # base held
    entry_cash = 0.0    # quote committed at entry (for net per-trade return)
    entry = 0.0
    trades = 0
    wins = 0
    trade_returns = []  # net % return of each closed trade (after fees)
    peak = 1.0
    max_dd = 0.0

    for i in range(len(closes)):
        price = closes[i]
        # mark-to-market equity
        equity = cash + qty * price
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

        if qty > 0:
            change = (price / entry - 1) * 100
            hit_sl = p["stop_loss_pct"] and change <= -p["stop_loss_pct"]
            hit_tp = p["take_profit_pct"] and change >= p["take_profit_pct"]
            if hit_sl or hit_tp or signals[i] == "sell":
                proceeds = qty * price * (1 - fee_pct / 100)
                trade_returns.append((proceeds / entry_cash - 1) * 100
                                     if entry_cash else 0.0)
                if proceeds > entry_cash:
                    wins += 1
                cash = proceeds
                qty = 0.0
                trades += 1
                entry = entry_cash = 0.0
                continue

        if qty == 0 and signals[i] == "buy":
            entry_cash = cash
            qty = (cash * (1 - fee_pct / 100)) / price
            entry = price
            cash = 0.0

    final_equity = cash + qty * closes[-1] if closes else 1.0
    return_pct = (final_equity - 1.0) * 100
    win_rate = (wins / trades * 100) if trades else 0.0

    # Consistency (Sharpe-like): mean per-trade return / its spread. A strategy
    # that grinds out steady small wins now out-scores one with the same total
    # return made of a few wild swings — which generalises far better live.
    consistency = 0.0
    if len(trade_returns) >= 2:
        avg = sum(trade_returns) / len(trade_returns)
        var = sum((r - avg) ** 2 for r in trade_returns) / len(trade_returns)
        consistency = avg / (var ** 0.5 + 0.5)      # +0.5% damps tiny samples

    # Score rewards return + consistency, penalises drawdown, REWARDS a high win
    # rate, and punishes thin samples so a single lucky trade can't win the grid.
    score = (return_pct - 0.5 * max_dd + (win_rate - 50.0) * 0.10
             + 3.0 * consistency)
    if 0 < trades < MIN_TRADES:
        score -= (MIN_TRADES - trades) * 1.5
    if trades == 0:
        score = -999.0

    return {
        "return_pct": round(return_pct, 2),
        "trades": trades,
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_dd, 2),
        "score": round(score, 2),
    }
