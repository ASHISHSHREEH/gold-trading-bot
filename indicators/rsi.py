import pandas as pd
import numpy as np
import logging
from typing import Union, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RSICalculator:
    def __init__(self, period: int = 14, overbought: float = 70.0, oversold: float = 30.0):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

    def calculate_rsi(self, data: Union[pd.DataFrame, pd.Series]) -> pd.Series:
        # Extract 'close' column safely
        if isinstance(data, pd.DataFrame):
            # Check for lowercase 'close' (standardized by our fetcher)
            if 'close' in data.columns:
                prices = data['close']
            elif 'Close' in data.columns: # Handle capitalization just in case
                prices = data['Close']
            else:
                raise ValueError("DataFrame missing 'close' column")
        else:
            prices = data

        if len(prices) < self.period + 1:
            return pd.Series(np.nan, index=prices.index)

        # Calculation
        delta = prices.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        avg_gain = gain.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.fillna(100)

    def analyze_latest(self, data: pd.DataFrame) -> Dict[str, Any]:
        rsi_series = self.calculate_rsi(data)
        
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return {"rsi": None, "signal": "NEUTRAL", "message": "Insufficient Data"}

        val = float(rsi_series.iloc[-1])
        
        signal = "NEUTRAL"
        if val >= self.overbought: signal = "SELL"
        elif val <= self.oversold: signal = "BUY"

        return {
            "rsi": round(val, 2),
            "signal": signal,
            "message": f"RSI is {signal} ({val:.2f})"
        }