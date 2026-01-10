"""
MetalPriceAPI Data Fetcher Module

This module provides the MetalPriceDataFetcher class for retrieving gold (XAU)
price data from the MetalPriceAPI. It supports latest prices, historical data,
and automatic retries.

Example Usage:
    from data.fetcher import MetalPriceDataFetcher

    try:
        fetcher = MetalPriceDataFetcher()
        
        # 1. Get latest gold price in JPY
        df = fetcher.get_latest_price()
        print(f"Current XAU/JPY: {df['price'].iloc[0]}")

        # 2. Get historical price for specific date
        df_historical = fetcher.get_historical_price("2025-01-01")
        print(df_historical)

        # 3. Get price range (if you have premium plan)
        df_range = fetcher.get_price_range("2025-01-01", "2025-01-10")
        print(df_range)

    except Exception as e:
        print(f"Error: {e}")
"""

import os
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MetalPriceDataFetcher:
    """
    A class to fetch gold (XAU/JPY) price data from MetalPriceAPI.
    
    Free tier limitations:
    - 50 requests per month
    - Latest prices only (no historical data on free tier)
    """

    BASE_URL = "https://api.metalpriceapi.com/v1"

    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize the fetcher by loading API key from environment variables.

        Args:
            env_path (str, optional): Path to specific .env file. Defaults to None.

        Raises:
            ValueError: If API key is missing.
        """
        # Load environment variables
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()

        self.api_key = os.getenv("METALPRICE_API_KEY")
        self._validate_config()
        
        logger.info("MetalPriceAPI client initialized.")

    def _validate_config(self) -> None:
        """
        Validate that the API key is present.

        Raises:
            ValueError: If API key is missing.
        """
        if not self.api_key:
            error_msg = "Missing required environment variable: METALPRICE_API_KEY"
            logger.critical(error_msg)
            raise ValueError(error_msg)

    def _retry_request(self, url: str, params: Dict, max_retries: int = 3) -> Dict:
        """
        Execute an API request with retry logic.

        Args:
            url (str): The API endpoint URL.
            params (Dict): Query parameters for the request.
            max_retries (int): Number of retry attempts.

        Returns:
            Dict: The JSON response from the API.

        Raises:
            ConnectionError: If all retries fail.
        """
        attempts = 0
        while attempts < max_retries:
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()  # Raise exception for bad status codes
                return response.json()
            except requests.exceptions.RequestException as e:
                attempts += 1
                wait_time = 2 ** attempts  # Exponential backoff
                logger.warning(
                    f"Request failed: {e}. Retrying in {wait_time}s ({attempts}/{max_retries})..."
                )
                if attempts < max_retries:
                    time.sleep(wait_time)
        
        raise ConnectionError(f"API request failed after {max_retries} attempts.")

    def validate_connection(self) -> bool:
        """
        Test the API connection by fetching latest price.

        Returns:
            bool: True if connection is successful, False otherwise.
        """
        try:
            url = f"{self.BASE_URL}/latest"
            params = {
                "api_key": self.api_key,
                "base": "XAU",
                "currencies": "JPY"
            }
            response = self._retry_request(url, params)
            
            if response.get("success"):
                logger.info("API connection validated successfully.")
                return True
            else:
                logger.error(f"API returned error: {response.get('error', {}).get('info')}")
                return False
                
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return False

    def get_latest_price(self) -> pd.DataFrame:
        """
        Fetch the latest gold (XAU/JPY) price.

        Returns:
            pd.DataFrame: DataFrame with columns [timestamp, price].
        """
        try:
            url = f"{self.BASE_URL}/latest"
            params = {
                "api_key": self.api_key,
                "base": "XAU",
                "currencies": "JPY"
            }
            
            logger.info("Fetching latest XAU/JPY price...")
            response = self._retry_request(url, params)
            
            if not response.get("success"):
                error_msg = response.get("error", {}).get("info", "Unknown error")
                logger.error(f"API error: {error_msg}")
                return pd.DataFrame()
            
            # Extract data
            timestamp = datetime.fromtimestamp(response.get("timestamp", time.time()))
            rates = response.get("rates", {})
            price = rates.get("JPY")
            
            if price is None:
                logger.warning("No JPY rate found in response.")
                return pd.DataFrame()
            
            # Create DataFrame
            data = {
                "timestamp": [timestamp],
                "price": [price]
            }
            df = pd.DataFrame(data)
            
            logger.info(f"Successfully fetched price: {price} JPY")
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch latest price: {e}")
            return pd.DataFrame()

    def get_historical_price(self, date: str) -> pd.DataFrame:
        """
        Fetch historical gold price for a specific date.
        
        Note: This may require a paid plan on MetalPriceAPI.

        Args:
            date (str): Date in YYYY-MM-DD format.

        Returns:
            pd.DataFrame: DataFrame with columns [timestamp, price].
        """
        try:
            url = f"{self.BASE_URL}/{date}"
            params = {
                "api_key": self.api_key,
                "base": "XAU",
                "currencies": "JPY"
            }
            
            logger.info(f"Fetching XAU/JPY price for {date}...")
            response = self._retry_request(url, params)
            
            if not response.get("success"):
                error_msg = response.get("error", {}).get("info", "Unknown error")
                logger.error(f"API error: {error_msg}")
                logger.warning("Historical data may require a paid plan.")
                return pd.DataFrame()
            
            # Extract data
            timestamp = datetime.strptime(date, "%Y-%m-%d")
            rates = response.get("rates", {})
            price = rates.get("JPY")
            
            if price is None:
                logger.warning("No JPY rate found in response.")
                return pd.DataFrame()
            
            # Create DataFrame
            data = {
                "timestamp": [timestamp],
                "price": [price]
            }
            df = pd.DataFrame(data)
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch historical price: {e}")
            return pd.DataFrame()

    def get_price_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch gold prices for a date range.
        
        Note: This requires multiple API calls and may hit rate limits.
        Consider upgrading to paid plan for frequent historical data access.

        Args:
            start_date (str): Start date in YYYY-MM-DD format.
            end_date (str): End date in YYYY-MM-DD format.

        Returns:
            pd.DataFrame: DataFrame with columns [timestamp, price].
        """
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            if start > end:
                logger.error("Start date must be before end date.")
                return pd.DataFrame()
            
            # Generate list of dates
            date_range = []
            current = start
            while current <= end:
                date_range.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
            
            logger.info(f"Fetching {len(date_range)} days of data...")
            logger.warning(f"This will use {len(date_range)} API calls. Free tier: 50 calls/month.")
            
            # Fetch data for each date
            all_data = []
            for date_str in date_range:
                df = self.get_historical_price(date_str)
                if not df.empty:
                    all_data.append(df)
                time.sleep(0.5)  # Rate limiting: don't hammer the API
            
            if not all_data:
                return pd.DataFrame()
            
            # Combine all data
            result_df = pd.concat(all_data, ignore_index=True)
            result_df = result_df.sort_values("timestamp").reset_index(drop=True)
            
            logger.info(f"Successfully fetched {len(result_df)} price points.")
            return result_df
            
        except Exception as e:
            logger.error(f"Failed to fetch price range: {e}")
            return pd.DataFrame()


# Example usage for testing
if __name__ == "__main__":
    try:
        fetcher = MetalPriceDataFetcher()
        
        # Test connection
        if fetcher.validate_connection():
            print("✓ Successfully connected to MetalPriceAPI!")
            
            # Get latest price
            df = fetcher.get_latest_price()
            if not df.empty:
                print("\n📊 Latest Gold Price (XAU/JPY):")
                print(df)
                print(f"\nPrice: ¥{df['price'].iloc[0]:,.2f}")
            else:
                print("❌ Failed to fetch latest price")
        else:
            print("❌ Failed to connect to MetalPriceAPI")
            
    except ValueError as ve:
        print(f"❌ Configuration Error: {ve}")
        print("\nMake sure you have set METALPRICE_API_KEY in your .env file")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")