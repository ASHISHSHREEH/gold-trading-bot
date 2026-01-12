import pandas as pd
import numpy as np
import logging
from typing import Union, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MACDCalculator:
    """
    A robust MACD (Moving Average Convergence Divergence) calculator.
    
    Features:
    - Configurable periods (Fast=12, Slow=26, Signal=9)
    - Crossover detection (Bullish/Bearish)
    - Signal strength analysis
    - Pandas DataFrame integration
    """

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        """
        Initialize the MACD Calculator.

        Args:
            fast_period (int): Period for the fast EMA (default 12).
            slow_period (int): Period for the slow EMA (default 26).
            signal_period (int): Period for the signal line EMA (default 9).
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

        # Validation
        if not (0 < fast_period < slow_period):
            raise ValueError("Fast period must be positive and less than slow period.")
        if signal_period <= 0:
            raise ValueError("Signal period must be positive.")

    def calculate_macd(self, data: Union[pd.DataFrame, pd.Series]) -> pd.DataFrame:
        """
        Calculate MACD, Signal line, and Histogram.

        Args:
            data (pd.DataFrame or pd.Series): Price data. If DataFrame, expects 'close' column.

        Returns:
            pd.DataFrame: Contains columns ['macd', 'signal', 'histogram']
        """
        # 1. Input Validation & Preparation
        if isinstance(data, pd.DataFrame):
            col_map = {c.lower(): c for c in data.columns}
            if 'close' not in col_map:
                logger.error("DataFrame missing 'close' column")
                raise ValueError("Input DataFrame must contain a 'close' column")
            prices = data[col_map['close']]
        elif isinstance(data, pd.Series):
            prices = data
        else:
            raise TypeError("Input must be a pandas DataFrame or Series")

        # Ensure sufficient data
        min_required = self.slow_period + self.signal_period
        if len(prices) < min_required:
            logger.warning(f"Insufficient data ({len(prices)}) for MACD calculation. Need at least {min_required}.")
            return pd.DataFrame(columns=['macd', 'signal', 'histogram'])

        # 2. Calculate EMAs (Exponential Moving Averages)
        # adjust=False matches the standard technical analysis definition (e.g. TradingView)
        ema_fast = prices.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = prices.ewm(span=self.slow_period, adjust=False).mean()

        # 3. Calculate MACD Line
        macd_line = ema_fast - ema_slow

        # 4. Calculate Signal Line
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()

        # 5. Calculate Histogram
        histogram = macd_line - signal_line

        # 6. Assemble DataFrame
        result_df = pd.DataFrame({
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        })
        
        # Clean up warm-up period (optional, but cleaner)
        # The first few values are often unreliable until the EMAs stabilize
        result_df.iloc[:self.slow_period-1] = np.nan

        return result_df

    def detect_crossover(self, macd_df: pd.DataFrame, index: int = -1) -> str:
        """
        Check for crossovers at a specific index.
        
        Returns:
            str: 'BULLISH', 'BEARISH', or 'NONE'
        """
        if len(macd_df) < 2:
            return "NONE"
            
        try:
            # Current values
            curr_hist = macd_df['histogram'].iloc[index]
            # Previous values
            prev_hist = macd_df['histogram'].iloc[index - 1]
            
            # Bullish: Histogram crosses from negative to positive
            if prev_hist <= 0 and curr_hist > 0:
                return "BULLISH"
            
            # Bearish: Histogram crosses from positive to negative
            if prev_hist >= 0 and curr_hist < 0:
                return "BEARISH"
                
            return "NONE"
            
        except IndexError:
            return "NONE"

    def analyze_latest(self, macd_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyze the latest MACD values to generate a comprehensive signal.

        Returns:
            Dict: {macd, signal_line, histogram, signal, strength, message}
        """
        if macd_df.empty or pd.isna(macd_df['macd'].iloc[-1]):
            return {
                "signal": "NEUTRAL",
                "message": "Insufficient data"
            }

        # Extract latest values
        curr_macd = macd_df['macd'].iloc[-1]
        curr_sig = macd_df['signal'].iloc[-1]
        curr_hist = macd_df['histogram'].iloc[-1]
        
        # Check crossover
        crossover = self.detect_crossover(macd_df)
        
        # Determine Signal & Strength
        signal_type = "NEUTRAL"
        strength = "WEAK"
        message = "MACD is trending neutrally."

        if crossover == "BULLISH":
            signal_type = "BUY"
            strength = "STRONG"
            message = "Bullish Crossover: MACD crossed above Signal line."
        elif crossover == "BEARISH":
            signal_type = "SELL"
            strength = "STRONG"
            message = "Bearish Crossover: MACD crossed below Signal line."
        else:
            # No crossover, check trend
            if curr_hist > 0:
                signal_type = "BUY" if curr_macd > 0 else "NEUTRAL" # Only strong buy if above zero line
                strength = "MODERATE" if curr_hist > macd_df['histogram'].iloc[-2] else "WEAK"
                message = "Bullish trend (No crossover)."
            elif curr_hist < 0:
                signal_type = "SELL" if curr_macd < 0 else "NEUTRAL"
                strength = "MODERATE" if curr_hist < macd_df['histogram'].iloc[-2] else "WEAK"
                message = "Bearish trend (No crossover)."

        return {
            "macd": round(curr_macd, 4),
            "signal_line": round(curr_sig, 4),
            "histogram": round(curr_hist, 4),
            "signal": signal_type,
            "strength": strength,
            "message": message
        }

# --- Standalone Usage Example ---
if __name__ == "__main__":
    print("--- Running MACD Calculator Test ---")
    
    # Generate dummy price data (sine wave to force crossovers)
    x = np.linspace(0, 10, 100)
    prices = 100 + 10 * np.sin(x)
    df = pd.DataFrame({'close': prices})
    
    # Initialize
    macd_calc = MACDCalculator()
    
    # Calculate
    macd_df = macd_calc.calculate_macd(df)
    
    # Analyze
    print("\nCalculated MACD DataFrame (Tail):")
    print(macd_df.tail())
    
    analysis = macd_calc.analyze_latest(macd_df)
    
    print("\n--- Latest Analysis ---")
    print(f"MACD Line:   {analysis['macd']}")
    print(f"Signal Line: {analysis['signal_line']}")
    print(f"Histogram:   {analysis['histogram']}")
    print(f"Signal:      {analysis['signal']} ({analysis['strength']})")
    print(f"Message:     {analysis['message']}")