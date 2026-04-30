"""
Average True Range (ATR) — Wilder's smoothing method.
Used for ATR-based stop loss and take profit placement.
Industry standard at BlackRock, JPMorgan, and every systematic desk.
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ATRCalculator:
    """
    Calculates ATR using Wilder's EMA (the correct method).
    Simple rolling average ATR is NOT used — it understates volatility
    during regime changes, which causes stops to be placed too tight.
    """

    def __init__(self, period: int = 14):
        if period < 2:
            raise ValueError("ATR period must be >= 2")
        self.period = period

    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute ATR for the full DataFrame.

        Args:
            df: DataFrame with columns 'high', 'low', 'close'

        Returns:
            pd.Series of ATR values, same index as df
        """
        required = {"high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"DataFrame must contain columns: {required}")

        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        prev_close = close.shift(1)

        # True Range = max(H-L, |H-Cprev|, |L-Cprev|)
        tr = pd.concat(
            [high - low,
             (high - prev_close).abs(),
             (low  - prev_close).abs()],
            axis=1
        ).max(axis=1)

        # Wilder smoothing: EWM with alpha = 1/period
        atr = tr.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()

        return atr

    def get_latest(self, df: pd.DataFrame) -> Optional[float]:
        """
        Return the most recent ATR value.
        Returns None if data is insufficient.
        """
        if len(df) < self.period + 1:
            logger.warning(
                f"ATR({self.period}): need {self.period + 1} bars, got {len(df)}"
            )
            return None

        atr_series = self.calculate(df)
        val = atr_series.iloc[-1]

        if pd.isna(val):
            return None

        return float(val)

    def get_atr_bands(
        self,
        df: pd.DataFrame,
        sl_multiplier: float = 1.5,
        tp_multiplier: float = 3.0,
        direction: str = "LONG"
    ) -> Optional[dict]:
        """
        Calculate ATR-based SL and TP levels for a trade entry at current close.

        Args:
            df: OHLCV DataFrame
            sl_multiplier: ATR multiple for stop loss distance
            tp_multiplier: ATR multiple for take profit distance
            direction: 'LONG' or 'SHORT'

        Returns:
            dict with keys: atr, entry, stop_loss, take_profit, rr_ratio
        """
        atr = self.get_latest(df)
        if atr is None:
            return None

        entry = float(df["close"].iloc[-1])
        sl_dist = atr * sl_multiplier
        tp_dist = atr * tp_multiplier

        if direction.upper() == "LONG":
            stop_loss   = entry - sl_dist
            take_profit = entry + tp_dist
        else:
            stop_loss   = entry + sl_dist
            take_profit = entry - tp_dist

        rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0.0

        return {
            "atr":         round(atr, 5),
            "entry":       round(entry, 5),
            "stop_loss":   round(stop_loss, 5),
            "take_profit": round(take_profit, 5),
            "rr_ratio":    round(rr_ratio, 2),
        }
