"""
MT5DataFetcher — all market data comes from the MT5 terminal.
Replaces the old yfinance + MetalPriceAPI hybrid entirely.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # allows the module to load on machines without MT5 installed

import config

logger = logging.getLogger(__name__)

# MT5 timeframe map — extend as needed
_TF_MAP = {
    "M1":  1,    # mt5.TIMEFRAME_M1
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  16385,
    "H4":  16388,
    "D1":  16408,
}


def _tf_const(name: str):
    """Return the MT5 TIMEFRAME_* constant for a string like 'M15'."""
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not installed.")
    mapping = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }
    tf = mapping.get(name.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe: {name}")
    return tf


class MT5DataFetcher:
    """
    Thin wrapper around the MT5 Python API.
    One instance per bot session; call connect() at startup,
    disconnect() on shutdown.
    """

    def __init__(self):
        self._connected = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        if mt5 is None:
            logger.critical("MetaTrader5 package not installed. Run: pip install MetaTrader5")
            return False

        # Pass all credentials directly to initialize() so it can launch
        # the terminal automatically and log in without manual intervention.
        # This also ensures we connect to the correct terminal when multiple
        # MT5 installs exist (FxPro vs FBS vs generic).
        init_kwargs = dict(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        if config.MT5_PATH:
            init_kwargs["path"] = config.MT5_PATH

        if not mt5.initialize(**init_kwargs):
            logger.critical(f"mt5.initialize() failed: {mt5.last_error()}")
            logger.critical(
                "Make sure the FxPro MT5 terminal is installed and the path "
                "in MT5_PATH is correct."
            )
            return False

        info = mt5.account_info()
        logger.info(
            f"MT5 connected | Account: {info.login} | "
            f"Server: {info.server} | "
            f"Balance: {info.balance:.2f} {info.currency} | "
            f"Leverage: 1:{info.leverage}"
        )

        # Ensure symbol is visible in MarketWatch
        if not mt5.symbol_select(config.SYMBOL, True):
            # Symbol not found — search for gold alternatives and guide the user
            all_symbols = mt5.symbols_get()
            gold_symbols = [
                s.name for s in all_symbols
                if "XAU" in s.name.upper() or "GOLD" in s.name.upper()
            ] if all_symbols else []

            logger.error(
                f"Symbol '{config.SYMBOL}' not available on this account.\n"
                f"  Available gold symbols on FxPro: {gold_symbols}\n"
                f"  Update MT5_SYMBOL in your .env to one of the above."
            )
            mt5.shutdown()
            return False

        self._connected = True
        return True

    def disconnect(self):
        if mt5 is not None:
            mt5.shutdown()
        self._connected = False
        logger.info("MT5 disconnected.")

    # ── Market Data ────────────────────────────────────────────────────────────

    def get_historical_data(self, timeframe_str: str, count: int = 500) -> pd.DataFrame:
        """
        Return OHLCV DataFrame for the configured symbol.
        Index is a timezone-aware UTC DatetimeIndex.
        """
        tf = _tf_const(timeframe_str)
        rates = mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, count)

        if rates is None or len(rates) == 0:
            logger.error(
                f"No data for {config.SYMBOL} {timeframe_str}: {mt5.last_error()}"
            )
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["open", "high", "low", "close", "volume"]].copy()

    def get_current_tick(self) -> Optional[Dict[str, Any]]:
        """Return latest bid/ask/spread."""
        tick = mt5.symbol_info_tick(config.SYMBOL)
        if tick is None:
            logger.error(f"get_current_tick failed: {mt5.last_error()}")
            return None
        return {
            "bid":    tick.bid,
            "ask":    tick.ask,
            "spread": round(tick.ask - tick.bid, 5),
            "time":   datetime.fromtimestamp(tick.time),
        }

    # ── Account & Symbol Info ─────────────────────────────────────────────────

    def get_account_info(self) -> Dict[str, Any]:
        info = mt5.account_info()
        if info is None:
            logger.error(f"get_account_info failed: {mt5.last_error()}")
            return {}
        return {
            "balance":       info.balance,
            "equity":        info.equity,
            "margin":        info.margin,
            "free_margin":   info.margin_free,
            "margin_level":  info.margin_level,   # percent; 0 if no positions
            "currency":      info.currency,
            "leverage":      info.leverage,
            "profit":        info.profit,
        }

    def get_symbol_info(self) -> Dict[str, Any]:
        info = mt5.symbol_info(config.SYMBOL)
        if info is None:
            logger.error(f"get_symbol_info failed: {mt5.last_error()}")
            return {}
        return {
            "contract_size": info.trade_contract_size,  # e.g. 100 oz per lot
            "min_lot":       info.volume_min,
            "max_lot":       info.volume_max,
            "lot_step":      info.volume_step,
            "digits":        info.digits,
            "point":         info.point,
            "stops_level":   info.trade_stops_level,    # minimum stop distance in points
            "spread":        info.spread,
        }
