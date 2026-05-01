"""
Backtest data loader — fetches H1 / M15 / M5 bars from MT5 or saved CSV files.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from typing import Dict


class DataLoader:

    def load_from_mt5(self, symbol: str, bars: int = 50000) -> Dict[str, pd.DataFrame]:
        """
        Pull H1, M15, M5 from a running MT5 terminal.
        Call mt5.initialize() before this and mt5.shutdown() after.
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            raise RuntimeError("MetaTrader5 package not installed.")

        tf_map = {
            "H4":  mt5.TIMEFRAME_H4,
            "H1":  mt5.TIMEFRAME_H1,
            "M15": mt5.TIMEFRAME_M15,
            "M5":  mt5.TIMEFRAME_M5,
        }

        result = {}
        for name, tf in tf_map.items():
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
            if rates is None or len(rates) == 0:
                raise RuntimeError(
                    f"Failed to load {name} data for {symbol}: {mt5.last_error()}"
                )
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df.rename(columns={"tick_volume": "volume"}, inplace=True)
            result[name] = df[["time", "open", "high", "low", "close", "volume"]].copy()
            print(f"  [{name}] {len(df):,} bars  "
                  f"({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")

        return result

    def load_from_csv(
        self,
        h4_path: str,
        h1_path: str,
        m15_path: str,
        m5_path: str,
    ) -> Dict[str, pd.DataFrame]:
        """Load pre-saved CSV files (created by save_to_csv)."""
        result = {}
        for name, path in [("H4", h4_path), ("H1", h1_path), ("M15", m15_path), ("M5", m5_path)]:
            df = pd.read_csv(path)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            result[name] = df
            print(f"  [{name}] {len(df):,} bars  "
                  f"({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")
        return result

    def save_to_csv(self, data: Dict[str, pd.DataFrame], prefix: str = "backtest") -> None:
        """Save loaded data to CSV for offline backtesting."""
        for name, df in data.items():
            path = f"{prefix}_{name}.csv"
            df.to_csv(path, index=False)
            print(f"  Saved {path}  ({len(df):,} bars)")
