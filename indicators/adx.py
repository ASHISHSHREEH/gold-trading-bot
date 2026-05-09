"""
adx.py — Average Directional Index (ADX) for market regime detection.

ADX measures trend strength, not direction:
  ADX < 20  → ranging / choppy market  → RSI/MACD signals are unreliable
  ADX 20-40 → trending market          → signals are reliable
  ADX > 40  → strong trend             → momentum strategies work best

Used as a regime filter: only open new trades when ADX >= ADX_MIN_TREND.
"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ADXCalculator:

    def __init__(self, period: int = 14):
        self.period = period

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate ADX, +DI, -DI from OHLC data.

        Returns DataFrame with columns: adx, plus_di, minus_di
        """
        if len(df) < self.period * 2:
            empty = pd.DataFrame(index=df.index, columns=["adx", "plus_di", "minus_di"])
            return empty.fillna(0.0)

        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Directional movement
        up_move   = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move,   0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_dm_s  = pd.Series(plus_dm,  index=df.index)
        minus_dm_s = pd.Series(minus_dm, index=df.index)

        # Wilder smoothing
        atr_s      = self._wilder_smooth(tr,         self.period)
        plus_di_s  = 100 * self._wilder_smooth(plus_dm_s,  self.period) / atr_s.replace(0, np.nan)
        minus_di_s = 100 * self._wilder_smooth(minus_dm_s, self.period) / atr_s.replace(0, np.nan)

        dx = (100 * (plus_di_s - minus_di_s).abs() /
              (plus_di_s + minus_di_s).replace(0, np.nan))

        adx = self._wilder_smooth(dx.fillna(0), self.period)

        return pd.DataFrame({
            "adx":      adx,
            "plus_di":  plus_di_s.fillna(0),
            "minus_di": minus_di_s.fillna(0),
        }, index=df.index)

    def get_latest(self, df: pd.DataFrame) -> dict:
        """Returns {adx, plus_di, minus_di, is_trending} for the last bar."""
        result = self.calculate(df)
        if result.empty or result["adx"].isna().all():
            return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "is_trending": False}
        row = result.iloc[-1]
        adx_val = float(row["adx"])
        return {
            "adx":         round(adx_val, 1),
            "plus_di":     round(float(row["plus_di"]),  1),
            "minus_di":    round(float(row["minus_di"]), 1),
            "is_trending": adx_val >= 20.0,
        }

    @staticmethod
    def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
        """Wilder's smoothing (equivalent to EMA with alpha=1/period)."""
        result = series.copy().astype(float)
        alpha  = 1.0 / period
        for i in range(1, len(result)):
            result.iloc[i] = result.iloc[i - 1] * (1 - alpha) + result.iloc[i] * alpha
        return result
