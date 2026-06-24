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
_GEMINI_HOST = "https://generativelanguage.googleapis.com"
_RESOLVED = {"gemini_model": None, "groq_model": None}  # auto-discovered, cached

# Preference order when auto-picking a Gemini model. Free tier matters most here,
# so prefer the LIGHT, high-quota, non-"thinking" models first (gemini-2.5-flash
# has a much tighter free RPD and burns thinking tokens → frequent 429s). A
# lite/flash model is plenty for one-number sentiment classification.
_GEMINI_PREFS = ["gemini-2.0-flash-lite", "gemini-2.5-flash-lite",
                 "gemini-2.0-flash", "flash-lite", "gemini-1.5-flash",
                 "gemini-2.5-flash", "flash-latest", "flash"]

_PROMPT = (
    "You are a crypto market sentiment analyst. Read these recent headlines and "
    "judge the OVERALL near-term sentiment for the crypto market. Respond with "
    "ONLY a compact JSON object: {\"score\": <number from -1 to 1>, \"reason\": "
    "\"<max 12 words>\"} where -1 = very bearish, 0 = neutral, +1 = very bullish.\n\n"
    "Headlines:\n")


def _available_providers():
    """Providers to try, in order, limited to those whose key is set. With both
    keys present they're tried in turn so a 429/outage on one falls through to
    the other automatically. LLM_PROVIDER forces one to be tried first."""
    pref = (os.environ.get("LLM_PROVIDER", "") or "").lower()
    order = [pref] if pref in ("gemini", "groq") else []
    for p in ("gemini", "groq"):
        if p not in order:
            order.append(p)
    keys = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
    return [p for p in order if os.environ.get(keys[p])]


def _call(provider, prompt):
    return _call_gemini(prompt) if provider == "gemini" else _call_groq(prompt)


def _model_name(provider):
    if provider == "gemini":
        return _resolve_gemini_model((os.environ.get("GEMINI_API_KEY") or "").strip())
    return _resolve_groq_model((os.environ.get("GROQ_API_KEY") or "").strip())


def ask(prompt):
    """Generic one-shot LLM call across available providers (Gemini→Groq).
    Returns the raw text reply, or None if no provider/all fail. Used by the
    AI coach to critique the bot's own trade journal."""
    for provider in _available_providers():
        try:
            text = _call(provider, prompt)
            if text:
                return text
        except Exception:
            continue
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


def _gemini_list_models(key):
    """Model names this key can actually call generateContent on."""
    d = _get_json(f"{_GEMINI_HOST}/v1beta/models?key={key}",
                  {"User-Agent": "cryptobot/1.0"})
    out = []
    for m in d.get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append((m.get("name", "") or "").split("/")[-1])
    return [m for m in out if m]


def _pick_gemini_model(models):
    """Choose the best available flash model, avoiding preview/exp builds."""
    if not models:
        return None
    stable = [m for m in models
              if "preview" not in m.lower() and "exp" not in m.lower()] or models
    for pref in _GEMINI_PREFS:
        for m in stable:
            if pref in m.lower():
                return m
    return stable[0]


def _resolve_gemini_model(key):
    """Explicit GEMINI_MODEL wins; otherwise auto-discover and cache one."""
    env = os.environ.get("GEMINI_MODEL")
    if env:
        return env.strip()
    if _RESOLVED["gemini_model"]:
        return _RESOLVED["gemini_model"]
    try:
        chosen = _pick_gemini_model(_gemini_list_models(key))
    except Exception:
        chosen = None
    if chosen:
        _RESOLVED["gemini_model"] = chosen   # cache ONLY a real discovery
        return chosen
    return "gemini-flash-latest"             # temporary; not cached → retried


def _call_gemini(prompt):
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    model = _resolve_gemini_model(key)
    url = f"{_GEMINI_HOST}/v1beta/models/{model}:generateContent?key={key}"
    out = _post(url, {"contents": [{"parts": [{"text": prompt}]}]},
                {"Content-Type": "application/json"})
    return out["candidates"][0]["content"]["parts"][0]["text"]


# Groq model auto-discovery (free model ids change; a stale default 403/404s).
_GROQ_PREFS = ["llama-3.3-70b-versatile", "llama-3.1-70b", "70b-versatile",
               "70b", "versatile", "llama-3.1-8b-instant", "8b-instant",
               "instant", "llama"]


def _get_json(url, headers, retries=3):
    """GET JSON with a couple of retries (model-list calls occasionally blip)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
    raise last


def _groq_list_models(key):
    d = _get_json("https://api.groq.com/openai/v1/models",
                  {"Authorization": f"Bearer {key}", "User-Agent": "cryptobot/1.0"})
    return [m.get("id") for m in d.get("data", []) if m.get("id")]


def _pick_groq_model(models):
    if not models:
        return None
    chat = [m for m in models if not any(b in m.lower() for b in
            ("whisper", "tts", "guard", "embed", "vision"))] or models
    for pref in _GROQ_PREFS:
        for m in chat:
            if pref in m.lower():
                return m
    return chat[0]


def _resolve_groq_model(key):
    env = os.environ.get("GROQ_MODEL")
    if env:
        return env.strip()
    if _RESOLVED["groq_model"]:
        return _RESOLVED["groq_model"]
    try:
        chosen = _pick_groq_model(_groq_list_models(key))
    except Exception:
        chosen = None
    if chosen:
        _RESOLVED["groq_model"] = chosen     # cache ONLY a real discovery
        return chosen
    return "llama-3.3-70b-versatile"         # temporary; not cached → retried


def _call_groq(prompt):
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    model = _resolve_groq_model(key)
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
    """One-shot startup check across ALL available providers (falls through on a
    429/outage). Returns (ok, detail). Makes a tiny live call so an invalid key,
    wrong model, or exhausted quota is surfaced immediately."""
    provs = _available_providers()
    if not provs:
        return False, "no key set (using keyword fallback)"
    notes = []
    for provider in provs:
        model = _model_name(provider)
        try:
            text = _call(provider, "Reply with the single number 1.")
            if text and re.search(r"\d", text):
                return True, f"{provider}:{model}"
            notes.append(f"{provider}:{model} no usable text")
        except Exception as e:
            msg = str(e)[:90]
            if "429" in msg:
                notes.append(f"{provider}:{model} quota/rate 429")
            elif any(c in msg for c in ("400", "401", "403")):
                # distinguish a bad key from a bad model: if the key can list
                # models, the key is fine and the model was the problem.
                hint = "check the API key"
                if provider == "groq":
                    try:
                        avail = _groq_list_models(
                            (os.environ.get("GROQ_API_KEY") or "").strip())
                        if avail:
                            hint = "key OK — models: " + ", ".join(avail[:4])
                    except Exception:
                        hint = "key rejected (regenerate & re-paste, no spaces)"
                notes.append(f"{provider}:{model} {msg} → {hint}")
            else:
                notes.append(f"{provider}:{model} {msg}")
    detail = " | ".join(notes) + "  (keyword fallback + auto-retry)"
    if notes and all("429" in n for n in notes) and "groq" not in provs:
        detail += " — add a free GROQ_API_KEY for much higher quota"
    return False, detail


def sentiment(headlines, ttl=_TTL):
    """(score in [-1,1], reason) from an LLM, or (None, None) if unavailable.

    Tries each available provider in turn, so a 429/outage on one (e.g. Gemini's
    free quota) automatically falls through to the other (e.g. Groq)."""
    provs = _available_providers()
    if not provs or not headlines:
        return None, None
    titles = [h.get("title", "") if isinstance(h, dict) else str(h)
              for h in headlines][:25]
    cache_key = (tuple(provs), hash(tuple(titles)))
    now = time.time()
    if _CACHE["key"] == cache_key and (now - _CACHE["t"]) < ttl:
        return _CACHE["result"]
    prompt = _PROMPT + "\n".join(f"- {t}" for t in titles if t)
    for provider in provs:
        try:
            result = _parse(_call(provider, prompt))
            if result[0] is not None:
                _CACHE.update(t=now, key=cache_key, result=result)
                return result
        except Exception:
            continue
    return None, None
