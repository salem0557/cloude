"""Machine-learning confirmation model — the "يتعلّم" part #2.

Every self-update cycle the bot retrains a small classifier per symbol on the
latest candles. The model predicts the probability that price will be higher
``HORIZON`` bars from now. A buy is only allowed when both the technical signal
fires AND the model is sufficiently bullish, which filters out many bad entries.

scikit-learn is optional: if it (or numpy) isn't installed, ``predict_up`` just
returns ``None`` and the bot trades on the technical signal alone. So the bot
still works everywhere, and gets smarter when the ML deps are present.
"""

from __future__ import annotations

import os
from pathlib import Path

from indicators import sma_series, rsi_series, ema_series

HERE = Path(__file__).resolve().parent
MODELS_DIR = Path(os.environ.get("DATA_DIR", str(HERE))) / "models"
HORIZON = 4          # predict direction 4 bars ahead
UP_THRESHOLD = 0.0   # "up" means return > 0 over the horizon

try:  # optional heavy deps
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    HAVE_SKLEARN = True
except Exception:  # pragma: no cover - depends on environment
    HAVE_SKLEARN = False

_CACHE = {}  # symbol -> fitted model (kept in memory for the process)


def _features_at(closes, fast, slow, rsi_s, ema12, ema26, i):
    """Feature vector for bar ``i`` (returns None if not computable)."""
    if i < 60:
        return None
    if None in (fast[i], slow[i], rsi_s[i], ema12[i], ema26[i]):
        return None
    price = closes[i]
    if price == 0 or slow[i] == 0:
        return None
    return [
        fast[i] / slow[i] - 1.0,                 # trend
        (price / closes[i - 1] - 1.0),           # 1-bar return
        (price / closes[i - 5] - 1.0),           # 5-bar return
        (price / closes[i - 20] - 1.0),          # 20-bar return
        rsi_s[i] / 100.0,                        # momentum
        ema12[i] / ema26[i] - 1.0,               # macd-ish
        price / fast[i] - 1.0,                   # stretch from mean
    ]


def _build_xy(closes):
    fast = sma_series(closes, 7)
    slow = sma_series(closes, 25)
    rsi_s = rsi_series(closes, 14)
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    X, y = [], []
    for i in range(len(closes) - HORIZON):
        feats = _features_at(closes, fast, slow, rsi_s, ema12, ema26, i)
        if feats is None:
            continue
        future = closes[i + HORIZON] / closes[i] - 1.0
        X.append(feats)
        y.append(1 if future > UP_THRESHOLD else 0)
    return X, y


def train(symbol, closes):
    """Train and cache a model for ``symbol``. Returns accuracy or None."""
    if not HAVE_SKLEARN:
        return None
    X, y = _build_xy(closes)
    if len(X) < 80 or len(set(y)) < 2:
        return None
    try:
        model = GradientBoostingClassifier(
            n_estimators=80, max_depth=3, learning_rate=0.05, random_state=0
        )
        model.fit(np.array(X), np.array(y))
        _CACHE[symbol] = model
        MODELS_DIR.mkdir(exist_ok=True)
        # Persist via joblib if available; otherwise keep in-memory only.
        try:
            import joblib
            joblib.dump(model, MODELS_DIR / f"{symbol}.pkl")
        except Exception:
            pass
        acc = float(model.score(np.array(X), np.array(y)))
        return round(acc, 3)
    except Exception:
        return None


def predict_up(symbol, closes):
    """Probability (0-1) that price rises over the horizon, or None."""
    if not HAVE_SKLEARN:
        return None
    model = _CACHE.get(symbol)
    if model is None:
        try:
            import joblib
            path = MODELS_DIR / f"{symbol}.pkl"
            if path.exists():
                model = joblib.load(path)
                _CACHE[symbol] = model
        except Exception:
            model = None
    if model is None:
        return None
    fast = sma_series(closes, 7)
    slow = sma_series(closes, 25)
    rsi_s = rsi_series(closes, 14)
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    feats = _features_at(closes, fast, slow, rsi_s, ema12, ema26, len(closes) - 1)
    if feats is None:
        return None
    try:
        prob = float(model.predict_proba(np.array([feats]))[0][1])
        return round(prob, 3)
    except Exception:
        return None
