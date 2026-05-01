"""
Run the Gold Bot backtest.

Usage (from repo root):

  # Live data from MT5 terminal:
  python backtest/run_backtest.py

  # From saved CSV files (after first run with --save):
  python backtest/run_backtest.py --csv

  # Save data to CSV then run:
  python backtest/run_backtest.py --save

  # Override balance or bars:
  python backtest/run_backtest.py --balance 50000 --bars 100000
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import config
from backtest.backtest_engine import BacktestEngine
from backtest.data_loader     import DataLoader


def parse_args():
    p = argparse.ArgumentParser(description="Gold Bot Backtest")
    p.add_argument("--symbol",  default=config.SYMBOL,   help="Symbol (default: from config)")
    p.add_argument("--balance", type=float, default=10_000.0, help="Starting balance USD")
    p.add_argument("--bars",    type=int,   default=50_000,   help="Bars to load per timeframe")
    p.add_argument("--csv",  action="store_true", help="Load from saved CSV files")
    p.add_argument("--save", action="store_true", help="Save MT5 data to CSV then run")
    p.add_argument("--h1",  default="backtest_H1.csv",  help="H1 CSV path")
    p.add_argument("--m15", default="backtest_M15.csv", help="M15 CSV path")
    p.add_argument("--m5",  default="backtest_M5.csv",  help="M5 CSV path")
    return p.parse_args()


def main():
    args    = parse_args()
    symbol  = args.symbol
    loader  = DataLoader()

    print("\n" + "=" * 55)
    print("  GOLD BOT BACKTEST")
    print(f"  Symbol  : {symbol}")
    print(f"  Balance : ${args.balance:,.0f}")
    print(f"  Bars    : {args.bars:,} per timeframe")
    print("=" * 55)

    if args.csv:
        print("\n[*] Loading from CSV files...")
        data = loader.load_from_csv(
            h1_path  = args.h1,
            m15_path = args.m15,
            m5_path  = args.m5,
        )
    else:
        print("\n[*] Connecting to MT5...")
        try:
            import MetaTrader5 as mt5
        except ImportError:
            print("[!] MetaTrader5 package not installed.")
            sys.exit(1)

        init_kwargs = dict(
            login    = config.MT5_LOGIN,
            password = config.MT5_PASSWORD,
            server   = config.MT5_SERVER,
        )
        if config.MT5_PATH:
            init_kwargs["path"] = config.MT5_PATH

        if not mt5.initialize(**init_kwargs):
            print(f"[!] MT5 init failed: {mt5.last_error()}")
            sys.exit(1)

        try:
            print(f"[*] Loading {args.bars:,} bars for {symbol}...")
            data = loader.load_from_mt5(symbol, bars=args.bars)

            if args.save:
                print("\n[*] Saving to CSV for offline use...")
                loader.save_to_csv(data, prefix=f"backtest_{symbol}")
        finally:
            mt5.shutdown()

    engine = BacktestEngine(initial_balance=args.balance)
    stats  = engine.run(data)
    engine.print_report(stats)


if __name__ == "__main__":
    main()
