"""LLM-powered news sentiment — FREE tiers (Google Gemini or Groq).

Keyword counting is brittle ("not a hack" still trips on 'hack'; sarcasm and
context are invisible). When a free LLM key is provided the bot instead asks a
small fast model to READ the latest headlines and return ONE market-sentiment
number in [-1, 1] plus a short reason.

Provide ONE of these (both have a no-credit-card free tier):
  GEMINI_API_KEY  Google AI Studio  — https://aistudio.google.com/apikey
  GROQ_API_KEY    Groq              — https://console.groq.com/keys

Optional overrides:
  LLM_PROVIDER = gemini | groq        (auto-detected from whichever key is set)
  GEMINI_MODEL = gemini-flash-latest  (default)
  GROQ_MODEL   = llama-3.3-70b-versatile (default)

``sentiment(headlines)`` returns (score, reason) or (None, None) when no key is
set or anything fails — the caller then falls back to the keyword scorer, so the
bot works perfectly without a key. Cached for ``ttl`` seconds (default 1800) to
stay comfortably inside the free quotas.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

_TTL = 1800
_RETRY_CODES = {429, 500, 502, 503, 504}   # transient — worth a quick retry
_CACHE = {"t": 0.0, "key": None, "result": (None, None)}

_PROMPT = (
    "You are a crypto market sentiment analyst. Read these recent headlines and "
    "judge the OVERALL near-term sentiment for the crypto market. Respond with "
    "ONLY a compact JSON object: {\"score\": <number from -1 to 1>, \"reason\": "
    "\"<max 12 words>\"} where -1 = very bearish, 0 = neutral, +1 = very bullish.\n\n"
    "Headlines:\n")


def _provider():
    p = (os.environ.get("LLM_PROVIDER", "") or "").lower()
    if p in ("gemini", "groq"):
        return p
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def _post(url, payload, headers, timeout=25, retries=3):
    """POST JSON with a short retry on transient server errors (503/429/...).

    Provider endpoints occasionally return 503 when momentarily overloaded; a
    couple of backed-off retries turn those blips into a success instead of an
    unnecessary fallback to keyword scoring."""
    data = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in _RETRY_CODES and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last


def _call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    out = _post(url, {"contents": [{"parts": [{"text": prompt}]}]},
                {"Content-Type": "application/json"})
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(prompt):
    key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    url = "https://api.groq.com/openai/v1/chat/completions"
    out = _post(url, {"model": model, "temperature": 0,
                      "messages": [{"role": "user", "content": prompt}]},
                {"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    return out["choices"][0]["message"]["content"]


def _parse(text):
    """Pull a {score, reason} out of the model's reply, robust to extra prose."""
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
            score = float(obj.get("score"))
            reason = str(obj.get("reason", ""))[:80]
            return max(-1.0, min(1.0, score)), reason
    except Exception:
        pass
    # last resort: first signed float in the text
    m = re.search(r"-?\d*\.?\d+", text or "")
    if m:
        try:
            return max(-1.0, min(1.0, float(m.group(0)))), "llm"
        except Exception:
            return None, None
    return None, None


def probe():
    """One-shot startup check: is a working LLM sentiment provider configured?

    Returns (ok: bool, detail: str). Makes a tiny live call so an invalid key or
    wrong model name is caught immediately instead of silently falling back to
    keyword scoring forever.
    """
    provider = _provider()
    if not provider:
        return False, "no key set (using keyword fallback)"
    model = (os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
             if provider == "gemini"
             else os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"))
    try:
        text = (_call_gemini("Reply with the single number 1.")
                if provider == "gemini"
                else _call_groq("Reply with the single number 1."))
        if text and re.search(r"\d", text):
            return True, f"{provider}:{model}"
        return False, f"{provider}:{model} returned no usable text"
    except Exception as e:
        msg = str(e)
        if "404" in msg:
            msg += "  → wrong model name? set GEMINI_MODEL / GROQ_MODEL"
        elif "400" in msg or "401" in msg or "403" in msg:
            msg += "  → check the API key"
        return False, f"{provider}:{model} — {msg[:120]}"


def sentiment(headlines, ttl=_TTL):
    """(score in [-1,1], reason) from an LLM, or (None, None) if unavailable."""
    provider = _provider()
    if not provider or not headlines:
        return None, None
    titles = [h.get("title", "") if isinstance(h, dict) else str(h)
              for h in headlines][:25]
    cache_key = (provider, hash(tuple(titles)))
    now = time.time()
    if _CACHE["key"] == cache_key and (now - _CACHE["t"]) < ttl:
        return _CACHE["result"]
    prompt = _PROMPT + "\n".join(f"- {t}" for t in titles if t)
    try:
        text = _call_gemini(prompt) if provider == "gemini" else _call_groq(prompt)
        result = _parse(text)
    except Exception:
        result = (None, None)
    if result[0] is not None:
        _CACHE.update(t=now, key=cache_key, result=result)
    return result
