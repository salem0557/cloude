"""The AI "brain" — a Claude-powered crypto-broker reasoning layer.

It sits on top of the mechanical bot and adds judgement: it reads the market
context (price, indicators, news sentiment, fear & greed) plus a self-maintained
"playbook" of best practices, then returns a reasoned BUY/SELL/HOLD decision
with a confidence and a written rationale. It also powers the chat box and can
refresh its playbook from the live web.

Model routing ("smart mix"):
  * routine per-position reviews  -> Sonnet 4.6  (fast, cheaper)
  * entry decisions / big calls   -> Opus 4.8    (deepest reasoning)

Everything degrades safely: if the `anthropic` package or an API key is missing,
`Brain.available` is False and the bot runs on its mechanical logic alone.

NOT financial advice. The brain can be confidently wrong; hard risk limits in
the bot always apply regardless of what it decides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

MODEL_ROUTINE = "claude-sonnet-4-6"
MODEL_BIG = "claude-opus-4-8"

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["action", "confidence", "reason"],
    "additionalProperties": False,
}

BROKER_SYSTEM = """You are a disciplined senior crypto spot-trading broker advising an automated bot.
You weigh: trend (moving averages), momentum (RSI), recent returns, market sentiment
(news + Fear & Greed), and the trader's playbook of best practices.

Rules:
- Spot only, long-only. Capital preservation first.
- Be skeptical and decisive. Do NOT buy into strongly negative breaking news or
  blow-off tops; favour buying strength in healthy uptrends or sound dips.
- Output ONLY the decision in the required schema: action (buy/sell/hold),
  confidence 0-1, and a one- or two-sentence reason. Be honest about uncertainty.
- You are not a guarantee of profit. When unsure, prefer "hold"."""


class Brain:
    def __init__(self, data_dir, log_fn=print):
        self.log = log_fn
        self.data_dir = Path(data_dir)
        self.playbook_file = self.data_dir / "playbook.md"
        self.client = None
        self.available = False
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=key)
            self.available = True
        except Exception as e:  # package missing or init failed
            self.log(f"🧠 brain disabled: {e}")

    # ----------------------------- playbook -----------------------------
    def read_playbook(self):
        try:
            return self.playbook_file.read_text(encoding="utf-8")[:6000]
        except Exception:
            return "(no playbook yet)"

    def update_playbook(self):
        """Search the web for current best practices and rewrite the playbook."""
        if not self.available:
            return False
        try:
            resp = self.client.messages.create(
                model=MODEL_ROUTINE,
                max_tokens=1500,
                system=("You maintain a concise crypto spot-trading playbook. "
                        "Search the web for current, reputable best practices on "
                        "risk management, entries/exits, and market-regime reading, "
                        "then output a tight markdown playbook (<400 words). "
                        "No hype, no specific coin calls, no guarantees."),
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=[{"role": "user", "content":
                           "Update my crypto spot-trading best-practices playbook."}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            if text.strip():
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.playbook_file.write_text(text.strip(), encoding="utf-8")
                self.log("🧠 playbook updated from the web")
                return True
        except Exception as e:
            self.log(f"🧠 playbook update failed: {e}")
        return False

    # ----------------------------- decisions -----------------------------
    def decide(self, snapshot, big=False):
        """Return {action, confidence, reason, model} or None on failure."""
        if not self.available:
            return None
        model = MODEL_BIG if big else MODEL_ROUTINE
        system = [
            {"type": "text", "text": BROKER_SYSTEM},
            {"type": "text", "text": "PLAYBOOK:\n" + self.read_playbook(),
             "cache_control": {"type": "ephemeral"}},
        ]
        try:
            kwargs = dict(
                model=model,
                max_tokens=1200,
                system=system,
                output_config={"format": {"type": "json_schema",
                                           "schema": DECISION_SCHEMA},
                               "effort": "high" if big else "low"},
                messages=[{"role": "user",
                           "content": "Decide for this situation:\n"
                           + json.dumps(snapshot, ensure_ascii=False)}],
            )
            if big:
                kwargs["thinking"] = {"type": "adaptive"}
            resp = self.client.messages.create(**kwargs)
            text = next(b.text for b in resp.content if b.type == "text")
            data = json.loads(text)
            data["model"] = model
            return data
        except Exception as e:
            self.log(f"🧠 decide error: {e}")
            return None

    # ------------------------------- chat -------------------------------
    def chat(self, history, user_message, context):
        """Reply to the user in the dashboard chat box."""
        if not self.available:
            return "العقل غير مفعّل — أضِف ANTHROPIC_API_KEY لتفعيله."
        system = [
            {"type": "text", "text": BROKER_SYSTEM +
             "\nYou are also chatting with the bot's owner. Answer in the user's "
             "language (Arabic if they write Arabic), concise and practical. You "
             "may explain past trades and current views, but never promise profit."},
            {"type": "text", "text": "PLAYBOOK:\n" + self.read_playbook()},
            {"type": "text", "text": "LIVE CONTEXT:\n"
             + json.dumps(context, ensure_ascii=False)},
        ]
        msgs = [{"role": m["role"], "content": m["content"]}
                for m in history[-8:]]
        msgs.append({"role": "user", "content": user_message})
        try:
            resp = self.client.messages.create(
                model=MODEL_ROUTINE, max_tokens=1000, system=system, messages=msgs)
            return "".join(b.text for b in resp.content if b.type == "text") or "…"
        except Exception as e:
            return f"تعذّر الرد: {e}"
