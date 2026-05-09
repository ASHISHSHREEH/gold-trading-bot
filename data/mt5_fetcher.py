"""
MT5DataFetcher — all market data comes from the MT5 terminal.
Supports multiple symbols; every data method accepts an explicit symbol
argument so the bot can trade GOLD, indices, and FX from one session.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger(__name__)


def _tf_const(name: str):
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

        # Try auto-connect first (works when MT5 is open and logged in, same privilege level)
        if mt5.initialize():
            info = mt5.account_info()
            if info:
                logger.info(
                    f"MT5 connected (auto) | Account: {info.login} | Server: {info.server} | "
                    f"Balance: {info.balance:.2f} {info.currency} | Leverage: 1:{info.leverage}"
                )
                return self._post_connect()

        # Fallback: explicit credentials + optional path
        init_kwargs = dict(
            login    = config.MT5_LOGIN    if config.MT5_LOGIN    else None,
            password = config.MT5_PASSWORD if config.MT5_PASSWORD else None,
            server   = config.MT5_SERVER   if config.MT5_SERVER   else None,
        )
        init_kwargs = {k: v for k, v in init_kwargs.items() if v is not None}
        if config.MT5_PATH:
            init_kwargs["path"] = config.MT5_PATH

        if not mt5.initialize(**init_kwargs):
            logger.critical(f"mt5.initialize() failed: {mt5.last_error()}")
            return False

        info = mt5.account_info()
        logger.info(
            f"MT5 connected | Account: {info.login} | Server: {info.server} | "
            f"Balance: {info.balance:.2f} {info.currency} | Leverage: 1:{info.leverage}"
        )
        return self._post_connect()

    def _post_connect(self) -> bool:
        """Enable symbols in MarketWatch after a successful mt5.initialize()."""
        failed = []
        for sym in config.SYMBOLS:
            if not mt5.symbol_select(sym, True):
                failed.append(sym)

        if failed:
            logger.error(
                f"Symbols not available on this account: {failed}\n"
                f"  Tip: check MT5_SYMBOLS in .env against what the broker offers."
            )
            mt5.shutdown()
            return False

        self._connected = True
        logger.info(f"Trading symbols activated: {config.SYMBOLS}")
        return True

    def disconnect(self):
        if mt5 is not None:
            mt5.shutdown()
        self._connected = False
        logger.info("MT5 disconnected.")

    # ── Market Data ────────────────────────────────────────────────────────────

    def get_historical_data(
        self,
        timeframe_str: str,
        count: int = 500,
        symbol: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame for the given symbol (defaults to primary)."""
        sym = symbol or config.SYMBOL
        tf  = _tf_const(timeframe_str)
        rates = mt5.copy_rates_from_pos(sym, tf, 0, count)

        if rates is None or len(rates) == 0:
            logger.error(f"No data for {sym} {timeframe_str}: {mt5.last_error()}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["open", "high", "low", "close", "volume"]].copy()

    def get_current_tick(self, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sym  = symbol or config.SYMBOL
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            logger.error(f"get_current_tick({sym}) failed: {mt5.last_error()}")
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
            "balance":      info.balance,
            "equity":       info.equity,
            "margin":       info.margin,
            "free_margin":  info.margin_free,
            "margin_level": info.margin_level,
            "currency":     info.currency,
            "leverage":     info.leverage,
            "profit":       info.profit,
        }

    def get_symbol_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        sym  = symbol or config.SYMBOL
        info = mt5.symbol_info(sym)
        if info is None:
            logger.error(f"get_symbol_info({sym}) failed: {mt5.last_error()}")
            return {}
        return {
            "contract_size": info.trade_contract_size,
            "min_lot":       info.volume_min,
            "max_lot":       info.volume_max,
            "lot_step":      info.volume_step,
            "digits":        info.digits,
            "point":         info.point,
            "stops_level":   info.trade_stops_level,
            "spread":        info.spread,
        }
