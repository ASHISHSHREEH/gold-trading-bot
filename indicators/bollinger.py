import pandas as pd
import numpy as np
import logging
from typing import Union, Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BollingerBandsCalculator:
    """
    A robust Bollinger Bands Calculator.
    
    Features:
    - Configurable periods (default 20) and standard deviations (default 2.0).
    - Calculation of Upper, Middle (SMA), and Lower bands.
    - Advanced metrics: Bandwidth and %B.
    - Squeeze detection for breakout trading.
    - Position analysis (Overbought/Oversold identification).
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        """
        Initialize the Bollinger Bands Calculator.

        Args:
            period (int): Lookback period for SMA and Standard Deviation (default 20).
            std_dev (float): Multiplier for standard deviation (default 2.0).
        """
        self.period = period
        self.std_dev = std_dev

        if period < 2:
            raise ValueError("Period must be at least 2.")
        if std_dev <= 0:
            raise ValueError("Standard deviation multiplier must be positive.")

    def calculate_bands(self, data: Union[pd.DataFrame, pd.Series]) -> pd.DataFrame:
        """
        Calculate Bollinger Bands, Bandwidth, and %B.

        Args:
            data (pd.DataFrame or pd.Series): Price data. If DataFrame, expects 'close' column.

        Returns:
            pd.DataFrame: Columns ['upper', 'middle', 'lower', 'bandwidth', 'percent_b']
        """
        # 1. Input Validation & Preparation
        if isinstance(data, pd.DataFrame):
            # Case-insensitive search for 'close'
            col_map = {c.lower(): c for c in data.columns}
            if 'close' not in col_map:
                logger.error("DataFrame missing 'close' column")
                raise ValueError("Input DataFrame must contain a 'close' column")
            prices = data[col_map['close']]
        elif isinstance(data, pd.Series):
            prices = data
        else:
            raise TypeError("Input must be a pandas DataFrame or Series")

        if len(prices) < self.period:
            logger.warning(f"Insufficient data ({len(prices)}) for Bollinger period ({self.period}).")
            return pd.DataFrame(columns=['upper', 'middle', 'lower', 'bandwidth', 'percent_b'])

        # 2. Calculate Middle Band (SMA)
        middle_band = prices.rolling(window=self.period).mean()

        # 3. Calculate Standard Deviation
        # ddof=1 is standard for sample standard deviation
        std_dev_val = prices.rolling(window=self.period).std(ddof=1)

        # 4. Calculate Upper and Lower Bands
        upper_band = middle_band + (std_dev_val * self.std_dev)
        lower_band = middle_band - (std_dev_val * self.std_dev)

        # 5. Calculate Bandwidth
        # Bandwidth = (Upper - Lower) / Middle
        bandwidth = (upper_band - lower_band) / middle_band

        # 6. Calculate %B (Percent B)
        # %B = (Price - Lower) / (Upper - Lower)
        # Shows where price is relative to bands (1.0 = at Upper, 0.0 = at Lower)
        denom = upper_band - lower_band
        percent_b = (prices - lower_band) / denom.replace(0, np.nan) # Avoid div by zero

        # 7. Assemble DataFrame
        result_df = pd.DataFrame({
            'upper': upper_band,
            'middle': middle_band,
            'lower': lower_band,
            'bandwidth': bandwidth,
            'percent_b': percent_b
        })

        return result_df

    def get_position(self, price: float, upper: float, lower: float, middle: float) -> str:
        """
        Identify where the price is relative to the bands.
        """
        if pd.isna(price) or pd.isna(upper) or pd.isna(lower):
            return "UNKNOWN"

        if price > upper:
            return "ABOVE_UPPER"
        elif price < lower:
            return "BELOW_LOWER"
        
        # Check if near bands (within 10% of the band width from the band)
        band_range = upper - lower
        threshold = band_range * 0.1
        
        if price >= (upper - threshold):
            return "NEAR_UPPER"
        elif price <= (lower + threshold):
            return "NEAR_LOWER"
        else:
            return "MIDDLE"

    def is_squeeze(self, bandwidth: float, threshold: float = 0.02) -> bool:
        """
        Check if volatility is historically low (Squeeze).
        
        Args:
            bandwidth: Current bandwidth value.
            threshold: Squeeze threshold (e.g., 0.02 means width is 2% of price).
                       Alternatively, can compare against historical min bandwidth.
        """
        if pd.isna(bandwidth): return False
        return bandwidth < threshold

    def detect_walking_bands(self, prices: pd.Series, bands_df: pd.DataFrame, lookback: int = 3) -> str:
        """
        Detect if price is 'walking' (sticking to) the bands, indicating a strong trend.
        
        Returns: 'WALKING_UP', 'WALKING_DOWN', or 'NONE'
        """
        if len(prices) < lookback or len(bands_df) < lookback:
            return "NONE"

        recent_closes = prices.iloc[-lookback:]
        recent_upper = bands_df['upper'].iloc[-lookback:]
        recent_lower = bands_df['lower'].iloc[-lookback:]

        # Simple logic: consecutive closes above upper or below lower
        if all(c > u for c, u in zip(recent_closes, recent_upper)):
            return "WALKING_UP"
        if all(c < l for c, l in zip(recent_closes, recent_lower)):
            return "WALKING_DOWN"
            
        return "NONE"

    def analyze_latest(self, prices: Union[pd.Series, pd.DataFrame], bands_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Analyze the latest market condition using Bollinger Bands.
        
        Returns dictionary with comprehensive signal and metrics.
        """
        # Ensure we have clean inputs
        if isinstance(prices, pd.DataFrame):
            price_series = prices['close'] if 'close' in prices.columns else prices.iloc[:, 0]
        else:
            price_series = prices

        if bands_df is None or bands_df.empty:
            bands_df = self.calculate_bands(price_series)

        if bands_df.empty or pd.isna(bands_df['middle'].iloc[-1]):
            return {"signal": "NEUTRAL", "message": "Insufficient data"}

        # Extract latest values
        curr_price = float(price_series.iloc[-1])
        idx = -1
        upper = bands_df['upper'].iloc[idx]
        lower = bands_df['lower'].iloc[idx]
        middle = bands_df['middle'].iloc[idx]
        width = bands_df['bandwidth'].iloc[idx]
        pct_b = bands_df['percent_b'].iloc[idx]

        # Determine Position
        position = self.get_position(curr_price, upper, lower, middle)
        
        # Determine Signal (Mean Reversion Strategy)
        signal = "NEUTRAL"
        message = "Price is within bands."
        
        if position == "ABOVE_UPPER":
            signal = "SELL"
            message = "Price broke above Upper Band (Overbought)."
        elif position == "BELOW_LOWER":
            signal = "BUY"
            message = "Price broke below Lower Band (Oversold)."
        elif position == "NEAR_UPPER":
            message = "Price testing Upper Band."
        elif position == "NEAR_LOWER":
            message = "Price testing Lower Band."

        # Check for Squeeze (Low Volatility)
        # Using a dynamic threshold relative to recent history if simple threshold fails? 
        # For now, sticking to a simple absolute low width check or simply reporting status.
        is_sqz = self.is_squeeze(width, threshold=0.002) # Example threshold for forex/gold
        if is_sqz:
            message += " [SQUEEZE DETECTED] Expect explosive move."

        # Check for Walking Bands (Trend Continuation)
        walking = self.detect_walking_bands(price_series, bands_df)
        if walking == "WALKING_UP":
            signal = "BUY_TREND" # Override mean reversion Sell
            message = "Strong Uptrend: Walking up the bands."
        elif walking == "WALKING_DOWN":
            signal = "SELL_TREND" # Override mean reversion Buy
            message = "Strong Downtrend: Walking down the bands."

        return {
            "price": round(curr_price, 2),
            "upper": round(upper, 2),
            "lower": round(lower, 2),
            "middle": round(middle, 2),
            "bandwidth": round(width, 4),
            "percent_b": round(pct_b, 2),
            "position": position,
            "signal": signal,
            "squeeze": is_sqz,
            "message": message
        }

# --- Standalone Usage Example ---
if __name__ == "__main__":
    print("--- Running Bollinger Bands Test ---")
    
    # Generate dummy data with a trend and volatility expansion
    prices = [100 + i + (np.sin(i/2) * 5) for i in range(50)]
    # Add a spike at the end
    prices[-1] = prices[-1] + 10 
    
    df = pd.DataFrame({'close': prices})
    
    bb_calc = BollingerBandsCalculator(period=20, std_dev=2)
    bands = bb_calc.calculate_bands(df['close'])
    
    print("\nDataFrame Head (Last 5):")
    print(bands.tail())
    
    analysis = bb_calc.analyze_latest(df['close'], bands)
    
    print("\n--- Latest Analysis ---")
    print(f"Price:     {analysis['price']}")
    print(f"Bands:     {analysis['lower']} | {analysis['middle']} | {analysis['upper']}")
    print(f"Bandwidth: {analysis['bandwidth']}")
    print(f"Position:  {analysis['position']}")
    print(f"Signal:    {analysis['signal']}")
    print(f"Message:   {analysis['message']}")