"""AI trading coach — an "expert mentor" that critiques the bot's OWN results.

Once a day the bot hands its recent trade journal and live per-strategy / per-coin
track record to a free LLM (Gemini/Groq) and asks: *what am I doing wrong, and
what should I change?* The critique is logged for you to read, and the coach's
``avoid_coins`` list is fed back as a soft penalty so the bot actually stops
repeating a losing pattern — learning from its mistakes, not just from price
history.

Everything degrades gracefully: no LLM key / any error → returns None and the bot
just keeps trading on its rules.
"""

from __future__ import annotations

import json
import re

import news_ai

_PROMPT = (
    "You are a veteran crypto trading coach reviewing an automated spot bot's "
    "OWN recent results. Be concrete and critical but practical. Based ONLY on "
    "the data below, identify what's going wrong and what to change.\n\n"
    "Respond with ONLY a compact JSON object:\n"
    "{\"summary\": \"<2-3 sentences, plain language>\", "
    "\"mistakes\": \"<the top recurring mistake>\", "
    "\"avoid_coins\": [\"SYM\", ...], "   # coins to stop trading for now
    "\"reduce_risk\": <true|false>}\n\n")


def _fmt_perf(perf):
    out = []
    for scope in ("strat", "coin"):
        rows = (perf or {}).get(scope, {})
        if not rows:
            continue
        out.append(f"By {scope}:")
        for k, e in sorted(rows.items(), key=lambda kv: kv[1].get("pnl", 0)):
            n = e.get("n", 0)
            if n <= 0:
                continue
            wr = e.get("w", 0) / n * 100
            out.append(f"  {k}: {n} trades, win {wr:.0f}%, P/L {e.get('pnl',0):+.3f}")
    return "\n".join(out) or "(no closed trades yet)"


def _fmt_trades(trades, n=25):
    out = []
    for t in (trades or [])[-n:]:
        out.append(f"  {t.get('time','')[:16]} {t.get('side')} {t.get('symbol')} "
                   f"@{t.get('price')} {t.get('reason','')}")
    return "\n".join(out) or "(none)"


def _parse(text):
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(0))
        return {
            "summary": str(obj.get("summary", ""))[:400],
            "mistakes": str(obj.get("mistakes", ""))[:300],
            "avoid_coins": [str(s).upper() for s in obj.get("avoid_coins", [])][:10],
            "reduce_risk": bool(obj.get("reduce_risk", False)),
        }
    except Exception:
        return None


def critique(trades, perf):
    """Ask the LLM to review the journal+record. Returns a dict or None."""
    if not (trades or (perf and (perf.get("strat") or perf.get("coin")))):
        return None
    prompt = (_PROMPT + "LIVE TRACK RECORD:\n" + _fmt_perf(perf)
              + "\n\nRECENT TRADES:\n" + _fmt_trades(trades))
    text = news_ai.ask(prompt)
    if not text:
        return None
    return _parse(text)
