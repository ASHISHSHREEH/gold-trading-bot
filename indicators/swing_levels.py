"""
swing_levels.py — swing high/low detection, SL-hunt spike filter, breakout detector.
"""
import logging
from typing import Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


# ── Swing High / Low ───────────────────────────────────────────────────────────

def find_swing_low(df: pd.DataFrame, lookback: int = 15) -> Optional[float]:
    """
    Walk backwards through the last `lookback` candles to find the most recent
    swing low (a candle whose low is lower than both its neighbours).
    Falls back to the rolling minimum if no pivot found.
    """
    lows = df["low"].values
    n    = len(lows)
    for i in range(n - 2, max(n - lookback - 2, 1), -1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            return float(lows[i])
    return float(df["low"].iloc[-lookback:].min())


def find_swing_high(df: pd.DataFrame, lookback: int = 15) -> Optional[float]:
    """
    Walk backwards to find the most recent swing high.
    Falls back to rolling maximum.
    """
    highs = df["high"].values
    n     = len(highs)
    for i in range(n - 2, max(n - lookback - 2, 1), -1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            return float(highs[i])
    return float(df["high"].iloc[-lookback:].max())


# ── SL-Hunt Spike Filter ───────────────────────────────────────────────────────

def detect_sl_hunt(df: pd.DataFrame, wick_ratio: float = 2.5) -> Dict[str, Any]:
    """
    Detects if the last completed candle was a stop-hunt spike:
    - A candle with a wick >= wick_ratio × body size pointing one direction
    - Followed by the current candle closing back the other way

    Returns:
        {
          'is_hunt'   : bool,
          'direction' : 'BULL_HUNT' | 'BEAR_HUNT' | None,
                        BULL_HUNT = wick spiked down (hunted longs) then reversed up
                        BEAR_HUNT = wick spiked up  (hunted shorts) then reversed down
        }
    """
    if len(df) < 3:
        return {"is_hunt": False, "direction": None}

    spike   = df.iloc[-2]   # the spike candle (completed)
    current = df.iloc[-1]   # current candle (just closed)

    body        = abs(spike["close"] - spike["open"])
    body        = max(body, 1e-8)   # avoid /0

    lower_wick  = min(spike["open"], spike["close"]) - spike["low"]
    upper_wick  = spike["high"] - max(spike["open"], spike["close"])

    # Bear spike hunt: long lower wick, current candle closes above the spike's open
    bear_hunt = (
        lower_wick >= wick_ratio * body
        and current["close"] > max(spike["open"], spike["close"])
    )

    # Bull spike hunt: long upper wick, current candle closes below the spike's open
    bull_hunt = (
        upper_wick >= wick_ratio * body
        and current["close"] < min(spike["open"], spike["close"])
    )

    if bear_hunt:
        return {"is_hunt": True, "direction": "BULL_HUNT"}   # hunted longs, now reversing up? No — hunted SL below, price reverses up
    if bull_hunt:
        return {"is_hunt": True, "direction": "BEAR_HUNT"}
    return {"is_hunt": False, "direction": None}


# ── Breakout + Retest Detector ─────────────────────────────────────────────────

def detect_breakout_retest(
    df: pd.DataFrame,
    atr: float,
    lookback: int = 30,
    retest_window: int = 8,
    tolerance_atr: float = 0.3,
) -> Dict[str, Any]:
    """
    Detects a breakout of a recent high/low followed by a retest of that level.

    Logic:
      1. Find the highest high and lowest low over the last `lookback` candles
         (excluding the last `retest_window` candles — those are post-breakout)
      2. Check if price broke above that high or below that low in the last
         `retest_window` candles
      3. Check if current price has pulled back to within `tolerance_atr` × ATR
         of the broken level (the retest)

    Returns:
        {
          'breakout'      : bool,
          'type'          : 'BULL_RETEST' | 'BEAR_RETEST' | None,
          'level'         : float | None,   # the broken level being retested
          'bars_since_bo' : int | None,
        }
    """
    if len(df) < lookback + retest_window or atr <= 0:
        return {"breakout": False, "type": None, "level": None, "bars_since_bo": None}

    base_range  = df.iloc[-(lookback + retest_window) : -retest_window]
    post_range  = df.iloc[-retest_window:]
    current_close = float(df["close"].iloc[-1])
    tolerance     = tolerance_atr * atr

    resistance = float(base_range["high"].max())
    support    = float(base_range["low"].min())

    # Bull breakout: any candle in post_range closed above resistance
    if post_range["close"].max() > resistance:
        bars_since = int((post_range["close"] > resistance).values[::-1].argmax()) + 1
        if current_close >= resistance - tolerance:
            return {
                "breakout":      True,
                "type":          "BULL_RETEST",
                "level":         resistance,
                "bars_since_bo": bars_since,
            }

    # Bear breakout: any candle in post_range closed below support
    if post_range["close"].min() < support:
        bars_since = int((post_range["close"] < support).values[::-1].argmax()) + 1
        if current_close <= support + tolerance:
            return {
                "breakout":      True,
                "type":          "BEAR_RETEST",
                "level":         support,
                "bars_since_bo": bars_since,
            }

    return {"breakout": False, "type": None, "level": None, "bars_since_bo": None}
