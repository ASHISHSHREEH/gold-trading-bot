import pandas as pd
import numpy as np
import logging
from typing import Union, Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MovingAverageCalculator:
    """
    Moving Average Calculator & Trend Analyzer.
    
    Features:
    - Calculates SMA and EMA for arbitrary periods.
    - Robustly identifies Fast vs Slow MAs to prevent signal inversion.
    - Detects Golden Cross and Death Cross.
    - Analyzes Slope and Trend.
    """

    def __init__(self):
        pass

    def calculate_sma(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average."""
        if len(prices) < period:
            logger.warning(f"Insufficient data for SMA({period}).")
            return pd.Series(np.nan, index=prices.index)
        return prices.rolling(window=period).mean()

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            logger.warning(f"Insufficient data for EMA({period}).")
            return pd.Series(np.nan, index=prices.index)
        return prices.ewm(span=period, adjust=False).mean()

    def calculate_multiple_mas(self, prices: pd.Series, periods: List[int] = [50, 200], ma_type: str = 'SMA') -> pd.DataFrame:
        """
        Calculate multiple MAs. Returns columns 'ma_50', 'ma_200', etc.
        """
        ma_df = pd.DataFrame(index=prices.index)
        
        for p in periods:
            col_name = f"ma_{p}"
            try:
                if ma_type.upper() == 'EMA':
                    ma_df[col_name] = self.calculate_ema(prices, p)
                else:
                    ma_df[col_name] = self.calculate_sma(prices, p)
            except Exception as e:
                logger.error(f"Failed to calc {ma_type} {p}: {e}")
                ma_df[col_name] = np.nan
                
        return ma_df

    def _detect_cross(self, fast: pd.Series, slow: pd.Series, signal_type: str) -> Dict[str, Any]:
        """Helper to detect crosses in the last completed candle."""
        if len(fast) < 2 or len(slow) < 2:
            return {'detected': False, 'index': -1, 'message': "Insufficient data"}

        prev_fast, curr_fast = fast.iloc[-2], fast.iloc[-1]
        prev_slow, curr_slow = slow.iloc[-2], slow.iloc[-1]

        # Check for NaN values
        if np.isnan([prev_fast, curr_fast, prev_slow, curr_slow]).any():
             return {'detected': False, 'index': -1, 'message': "NaN values in MAs"}

        detected = False
        message = ""

        if signal_type == "GOLDEN":
            # Golden Cross: Fast crosses ABOVE Slow
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                detected = True
                message = f"Golden Cross Detected! Fast ({curr_fast:.2f}) crossed above Slow ({curr_slow:.2f})"

        elif signal_type == "DEATH":
            # Death Cross: Fast crosses BELOW Slow
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                detected = True
                message = f"Death Cross Detected! Fast ({curr_fast:.2f}) crossed below Slow ({curr_slow:.2f})"

        return {
            'detected': detected,
            'index': -1 if detected else None,
            'message': message
        }

    def detect_golden_cross(self, ma_fast: pd.Series, ma_slow: pd.Series) -> Dict[str, Any]:
        return self._detect_cross(ma_fast, ma_slow, "GOLDEN")

    def detect_death_cross(self, ma_fast: pd.Series, ma_slow: pd.Series) -> Dict[str, Any]:
        return self._detect_cross(ma_fast, ma_slow, "DEATH")

    def get_trend(self, price: float, ma_fast: float, ma_slow: float) -> str:
        if pd.isna(price) or pd.isna(ma_fast) or pd.isna(ma_slow):
            return "UNKNOWN"

        if price > ma_fast > ma_slow:
            return "STRONG_BULL"
        if price > ma_fast and price > ma_slow:
            return "BULL"
        if price < ma_fast < ma_slow:
            return "STRONG_BEAR"
        if price < ma_fast and price < ma_slow:
            return "BEAR"

        return "NEUTRAL"

    def get_slope(self, series: pd.Series, lookback: int = 3) -> str:
        if len(series) < lookback + 1: return "FLAT"
        
        current = series.iloc[-1]
        previous = series.iloc[-(lookback + 1)]
        
        if pd.isna(current) or pd.isna(previous): return "FLAT"

        change = current - previous
        if change > 0: return "RISING"
        if change < 0: return "FALLING"
        return "FLAT"

    def analyze_latest(self, prices: Union[pd.Series, pd.DataFrame], ma_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyze latest market state with robust column identification.
        """
        # 1. Extract Price
        if isinstance(prices, pd.DataFrame):
            col_map = {c.lower(): c for c in prices.columns}
            target_col = col_map.get('close', prices.columns[0])
            price_series = prices[target_col]
        else:
            price_series = prices

        if ma_df.empty or len(price_series) == 0:
            return {"signal": "NEUTRAL", "message": "No data"}

        curr_price = float(price_series.iloc[-1])

        # 2. BUG FIX: Robustly identify Fast vs Slow MA
        # We parse the column names (e.g. 'ma_50') to find the integer periods
        period_map = {}
        for col in ma_df.columns:
            try:
                # Split by '_' and take the last part as int (ma_50 -> 50)
                period = int(col.split('_')[-1])
                period_map[period] = col
            except ValueError:
                continue
        
        # Sort periods: Smallest is Fast, Largest is Slow
        sorted_periods = sorted(period_map.keys())
        
        if len(sorted_periods) < 2:
            return {"signal": "NEUTRAL", "message": "Need at least 2 MA columns for analysis"}

        fast_period = sorted_periods[0]  # e.g., 50
        slow_period = sorted_periods[-1] # e.g., 200
        
        fast_col = period_map[fast_period]
        slow_col = period_map[slow_period]

        # 3. Extract Values
        try:
            ma_fast_series = ma_df[fast_col]
            ma_slow_series = ma_df[slow_col]
            ma_fast = float(ma_fast_series.iloc[-1])
            ma_slow = float(ma_slow_series.iloc[-1])
        except Exception:
            return {"signal": "NEUTRAL", "message": "Error accessing MA data"}

        # 4. Run Logic
        trend = self.get_trend(curr_price, ma_fast, ma_slow)
        golden = self.detect_golden_cross(ma_fast_series, ma_slow_series)
        death = self.detect_death_cross(ma_fast_series, ma_slow_series)
        ma_slow_slope = self.get_slope(ma_slow_series)

        # 5. Signal Synthesis
        signal = "NEUTRAL"
        msg_parts = []

        if golden['detected']:
            signal = "BUY"
            msg_parts.append(f"GOLDEN CROSS: MA{fast_period} crossed above MA{slow_period}.")
        elif death['detected']:
            signal = "SELL"
            msg_parts.append(f"DEATH CROSS: MA{fast_period} crossed below MA{slow_period}.")

        if trend == "STRONG_BULL":
            msg_parts.append("Trend is Strongly Bullish.")
        elif trend == "STRONG_BEAR":
            msg_parts.append("Trend is Strongly Bearish.")

        # Mean Reversion Check
        if ma_slow != 0:
            dist = (curr_price - ma_slow) / ma_slow
            if abs(dist) > 0.15:
                msg_parts.append(f"Price extended {dist:.1%} from MA{slow_period}.")

        return {
            "price": round(curr_price, 2),
            "trend": trend,
            "ma_fast": round(ma_fast, 2),
            "ma_slow": round(ma_slow, 2),
            "ma_slow_slope": ma_slow_slope,
            "golden_cross": golden['detected'],
            "death_cross": death['detected'],
            "signal": signal,
            "message": " ".join(msg_parts) if msg_parts else f"Trend is {trend}"
        }