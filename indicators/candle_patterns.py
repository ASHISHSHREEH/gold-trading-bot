"""
candle_patterns.py — TA-Lib candlestick pattern detection for M5 candles.

Detects (in priority order, strongest first):
  Morning Star      → BULL
  Evening Star      → BEAR
  Bullish Engulfing → BULL
  Bearish Engulfing → BEAR
  Hammer            → BULL
  Shooting Star     → BEAR
  Doji              → NEUTRAL (reversal warning, no score bonus)

Returns the highest-priority match on the last closed bar.
Gracefully returns {"name": None, "bias": None} if TA-Lib is not installed.

Install: pip install TA-Lib
"""
import logging
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# (talib_func_name, human_label, bias, sign)
# sign: +1 = only match positive values, -1 = only negative, 0 = either non-zero
_PATTERN_CHECKS = [
    ("CDLMORNINGSTAR",  "MORNING_STAR",      "BULL",    +1),
    ("CDLEVENINGSTAR",  "EVENING_STAR",      "BEAR",    -1),
    ("CDLENGULFING",    "BULLISH_ENGULFING", "BULL",    +1),
    ("CDLENGULFING",    "BEARISH_ENGULFING", "BEAR",    -1),
    ("CDLHAMMER",       "HAMMER",            "BULL",     0),
    ("CDLSHOOTINGSTAR", "SHOOTING_STAR",     "BEAR",     0),
    ("CDLDOJI",         "DOJI",              "NEUTRAL",  0),
]

_talib_available: Optional[bool] = None   # lazy check, cached after first call


def _check_talib() -> bool:
    global _talib_available
    if _talib_available is None:
        try:
            import talib  # noqa: F401
            _talib_available = True
        except ImportError:
            logger.warning(
                "candle_patterns: TA-Lib not installed — pattern detection disabled. "
                "Run: pip install TA-Lib"
            )
            _talib_available = False
    return _talib_available


def detect_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Scan the last closed bar of `df` (iloc[-1]) for candlestick patterns.

    `df` must have columns: open, high, low, close (lowercase).

    Returns:
        {"name": "HAMMER", "bias": "BULL"}   — first matching pattern
        {"name": "DOJI",   "bias": "NEUTRAL"} — doji reversal warning
        {"name": None,     "bias": None}       — no pattern detected
    """
    if not _check_talib() or len(df) < 3:
        return {"name": None, "bias": None}

    import talib
    import numpy as np

    try:
        o = df["open"].astype(float).values
        h = df["high"].astype(float).values
        l = df["low"].astype(float).values
        c = df["close"].astype(float).values
    except KeyError as exc:
        logger.debug("candle_patterns: missing OHLC column %s", exc)
        return {"name": None, "bias": None}

    for func_name, label, bias, sign in _PATTERN_CHECKS:
        try:
            fn = getattr(talib, func_name)
            # Morning/Evening Star accept an optional penetration kwarg
            if func_name in ("CDLMORNINGSTAR", "CDLEVENINGSTAR"):
                result = fn(o, h, l, c, penetration=0.3)
            else:
                result = fn(o, h, l, c)

            val = int(result[-1])
            if val == 0:
                continue
            if sign == +1 and val <= 0:
                continue
            if sign == -1 and val >= 0:
                continue

            return {"name": label, "bias": bias}

        except Exception as exc:
            logger.debug("candle_patterns: %s failed — %s", func_name, exc)
            continue

    return {"name": None, "bias": None}
