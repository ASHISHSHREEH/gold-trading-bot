"""
MT5 Data Fetcher
Handles all communication with the MetaTrader 5 terminal:
  - Connection / authentication
  - Historical OHLCV bars
  - Live tick (bid/ask)
  - Account & symbol metadata
"""

import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

# Map our string keys to MT5 timeframe constants
TIMEFRAME_MAP: Dict[str, int] = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


class MT5DataFetcher:
    """
    Single-responsibility wrapper around the MT5 Python API.
    One instance lives for the entire bot session.
    """

    def __init__(self, login: int, password: str, server: str, symbol: str):
        self.login    = login
        self.password = password
        self.server   = server
        self.symbol   = symbol
        self._connected = False

    # ── Connection ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Initialize the MT5 terminal and log in.
        Raises RuntimeError on any failure so the caller can abort cleanly.
        """
        if not mt5.initialize():
            raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")

        authorized = mt5.login(self.login, password=self.password, server=self.server)
        if not authorized:
            mt5.shutdown()
            raise RuntimeError(
                f"MT5 login failed for account {self.login} "
                f"on {self.server}: {mt5.last_error()}"
            )

        info = mt5.account_info()
        logger.info(
            f"MT5 connected | Account: {info.login} | "
            f"Name: {info.name} | Server: {info.server} | "
            f"Balance: {info.balance:.2f} {info.currency} | "
            f"Leverage: 1:{info.leverage}"
        )

        # Ensure the symbol is visible in MarketWatch
        if not mt5.symbol_select(self.symbol, True):
            logger.warning(
                f"symbol_select({self.symbol}) failed — "
                f"symbol may not exist on this broker."
            )

        self._connected = True

    def disconnect(self) -> None:
        mt5.shutdown()
        self._connected = False
        logger.info("MT5 disconnected.")

    def is_connected(self) -> bool:
        return self._connected and mt5.terminal_info() is not None

    # ── Market Data ─────────────────────────────────────────────────────────

    def get_historical_data(self, timeframe_str: str, count: int = 500) -> pd.DataFrame:
        """
        Fetch the last `count` closed+current candles for self.symbol.

        Returns a DataFrame with lowercase columns:
            open, high, low, close, volume
        Index is a UTC DatetimeIndex.
        Returns empty DataFrame on any failure.
        """
        tf = TIMEFRAME_MAP.get(timeframe_str)
        if tf is None:
            logger.error(f"Unknown timeframe: {timeframe_str}. Valid: {list(TIMEFRAME_MAP)}")
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos(self.symbol, tf, 0, count)

        if rates is None or len(rates) == 0:
            logger.warning(
                f"No data returned for {self.symbol} {timeframe_str}: "
                f"{mt5.last_error()}"
            )
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)

        # MT5 returns tick_volume; rename to volume for indicator compatibility
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        return df[["open", "high", "low", "close", "volume"]].copy()

    def get_current_tick(self) -> Optional[Dict[str, Any]]:
        """
        Return the latest bid/ask tick for self.symbol.
        Returns None if the market is closed or data is unavailable.
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            logger.warning(f"No tick data for {self.symbol}: {mt5.last_error()}")
            return None

        return {
            "bid":    tick.bid,
            "ask":    tick.ask,
            "spread": round(tick.ask - tick.bid, 5),
            "time":   datetime.utcfromtimestamp(tick.time),
        }

    # ── Account & Symbol Metadata ───────────────────────────────────────────

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        info = mt5.account_info()
        if info is None:
            logger.error(f"account_info() failed: {mt5.last_error()}")
            return None

        return {
            "login":        info.login,
            "name":         info.name,
            "balance":      info.balance,
            "equity":       info.equity,
            "margin":       info.margin,
            "margin_free":  info.margin_free,
            "margin_level": info.margin_level,   # % — 0 means no open positions
            "profit":       info.profit,
            "currency":     info.currency,
            "leverage":     info.leverage,
        }

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        info = mt5.symbol_info(self.symbol)
        if info is None:
            logger.error(f"symbol_info({self.symbol}) failed: {mt5.last_error()}")
            return None

        return {
            "symbol":            info.name,
            "digits":            info.digits,
            "point":             info.point,
            "contract_size":     info.trade_contract_size,   # oz per lot (100 for XAUUSD)
            "volume_min":        info.volume_min,
            "volume_max":        info.volume_max,
            "volume_step":       info.volume_step,
            "stops_level":       info.trade_stops_level,     # min SL/TP distance in points
            "filling_mode":      info.filling_mode,
            "spread":            info.spread,
        }

    def validate_connection(self) -> bool:
        """Quick health-check used at startup."""
        df = self.get_historical_data("M1", count=5)
        return not df.empty
