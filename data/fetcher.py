"""
Hybrid Data Fetcher
- Historical Data: yfinance (Free, slightly delayed)
- Current Price: MetalPriceAPI (Real-time spot)
"""
import os
import logging
import requests
import pandas as pd
import yfinance as yf
from typing import Optional
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class GoldDataFetcher:
    # Gold Futures Ticker (Yahoo)
    YAHOO_TICKER = "GC=F"
    METALPRICE_URL = "https://api.metalpriceapi.com/v1/latest"

    def __init__(self, env_path: Optional[str] = None):
        load_dotenv(env_path) if env_path else load_dotenv()
        self.mp_api_key = os.getenv("METALPRICE_API_KEY")
        self.yf_ticker = yf.Ticker(self.YAHOO_TICKER)

    def get_historical_data(self, period: str = '1mo', interval: str = '1h') -> pd.DataFrame:
        """
        Fetch historical data from Yahoo Finance for RSI calculation.
        """
        try:
            logger.info(f"Fetching history from yfinance (period={period}, interval={interval})...")
            df = self.yf_ticker.history(period=period, interval=interval)
            
            if df.empty:
                logger.warning("yfinance returned no data.")
                return pd.DataFrame()

            # STANDARD: Convert columns to lowercase (Open -> open)
            df.columns = df.columns.str.lower()
            
            # Keep only OHLCV
            cols = ['open', 'high', 'low', 'close', 'volume']
            df = df[[c for c in cols if c in df.columns]]
            
            # Drop rows with NaN values
            df.dropna(inplace=True)
            
            return df

        except Exception as e:
            logger.error(f"yfinance error: {e}")
            return pd.DataFrame()

    def get_current_price(self) -> Optional[float]:
        """
        Get the precise live spot price from MetalPriceAPI.
        Fallback to yfinance if API key is missing or fails.
        """
        # 1. Try MetalPriceAPI first (More accurate)
        if self.mp_api_key:
            try:
                params = {
                    "api_key": self.mp_api_key,
                    "base": "XAU",
                    "currencies": "JPY"
                }
                response = requests.get(self.METALPRICE_URL, params=params, timeout=5)
                data = response.json()
                
                if data.get("success"):
                    price = data["rates"]["JPY"]
                    logger.info(f"MetalPriceAPI Price: {price}")
                    return price
                else:
                    logger.warning(f"MetalPriceAPI Error: {data.get('error')}")
            except Exception as e:
                logger.error(f"MetalPriceAPI Request Failed: {e}")

        # 2. Fallback to Yahoo Finance (Delayed but free)
        logger.info("Falling back to yfinance for current price...")
        try:
            df = self.yf_ticker.history(period='1d', interval='1m')
            if not df.empty:
                return df['Close'].iloc[-1]
        except Exception as e:
            logger.error(f"Fallback failed: {e}")
        
        return None

    def validate_connection(self) -> bool:
        """Simple check to ensure we can reach yfinance."""
        df = self.get_historical_data(period='1d', interval='1h')
        return not df.empty