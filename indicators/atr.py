"""
Wilder's Average True Range — the industry standard for volatility-based stops.

Why Wilder and not simple ATR?
Wilder's EWM (alpha = 1/period) weights recent bars more heavily, giving
faster reaction to volatility expansion — critical for intraday XAUUSD.
"""
import logging
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class ATRCalculator:
    """
    Computes Wilder ATR and derives SL/TP levels from it.

    Usage:
        calc = ATRCalculator(period=14)
        atr_value = calc.get_latest(df)
        bands = calc.get_atr_bands(df, sl_mult=1.5, tp_mult=3.0, direction='BUY')
    """

    def __init__(self, period: int = 14):
        self.period = period

    # ── Core Calculation ───────────────────────────────────────────────────────

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        high       = df["high"]
        low        = df["low"]
        prev_close = df["close"].shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr

    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """Return a full ATR Series aligned with df's index."""
        if len(df) < self.period + 1:
            logger.warning(
                f"ATR needs {self.period + 1} bars, only {len(df)} available."
            )
            return pd.Series(dtype=float, index=df.index)

        tr  = self._true_range(df)
        # alpha = 1/period → Wilder smoothing
        atr = tr.ewm(alpha=1.0 / self.period, min_periods=self.period, adjust=False).mean()
        return atr

    # ── Convenience Accessors ─────────────────────────────────────────────────

    def get_latest(self, df: pd.DataFrame) -> float:
        """Single scalar ATR value for the most recent candle."""
        s = self.calculate(df)
        if s.empty or pd.isna(s.iloc[-1]):
            return 0.0
        return float(s.iloc[-1])

    def get_atr_bands(
        self,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        direction: str,
        entry_price: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Compute entry, SL, TP and R:R ratio based on ATR multiples.

        Args:
            direction: 'BUY' / 'LONG'  or  'SELL' / 'SHORT'
            entry_price: override the close price when computing levels
        """
        atr = self.get_latest(df)
        if atr == 0.0:
            return {}

        price = entry_price if entry_price is not None else float(df["close"].iloc[-1])
        is_long = direction.upper() in ("BUY", "LONG")

        sl = price - atr * sl_mult if is_long else price + atr * sl_mult
        tp = price + atr * tp_mult if is_long else price - atr * tp_mult

        sl_dist = abs(price - sl)
        rr = (abs(tp - price) / sl_dist) if sl_dist > 0 else 0.0

        return {
            "atr":         round(atr,   5),
            "entry":       round(price, 5),
            "stop_loss":   round(sl,    5),
            "take_profit": round(tp,    5),
            "rr_ratio":    round(rr,    2),
        }
