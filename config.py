"""
Central configuration — single source of truth for all bot parameters.
All values are loaded from .env; constants are defined here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── MT5 Connection ──────────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── Symbol ──────────────────────────────────────────────────────────────────
SYMBOL       = os.getenv("MT5_SYMBOL", "XAUUSD")
MAGIC        = int(os.getenv("MT5_MAGIC", "20240101"))
SLIPPAGE     = int(os.getenv("MT5_SLIPPAGE", "20"))
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE", "DEMO")   # "DEMO" or "LIVE"

# ── Risk Management ─────────────────────────────────────────────────────────
RISK_PER_TRADE   = 0.01    # 1% of balance per trade
MAX_DAILY_LOSS   = 0.03    # 3% daily drawdown circuit-breaker
MAX_POSITIONS    = 3       # max concurrent open positions
MIN_RR_RATIO     = 2.0     # minimum risk:reward to take a trade

# ── ATR-based Stop Parameters ───────────────────────────────────────────────
ATR_PERIOD       = 14
ATR_SL_MULT      = 1.5     # stop loss   = 1.5 × ATR
ATR_TP_MULT      = 3.0     # take profit = 3.0 × ATR  (2:1 R:R minimum)

# ── Timeframes ──────────────────────────────────────────────────────────────
TREND_TIMEFRAME  = "M15"   # 15-min confirmed trend
ENTRY_TIMEFRAME  = "M1"    # 1-min tactical entry
TREND_CANDLES    = 200     # candles to fetch for trend TF
ENTRY_CANDLES    = 100     # candles to fetch for entry TF

# ── Indicator Periods ───────────────────────────────────────────────────────
RSI_PERIOD       = 14
RSI_OVERBOUGHT   = 70
RSI_OVERSOLD     = 30
MACD_FAST        = 12
MACD_SLOW        = 26
MACD_SIGNAL      = 9
BB_PERIOD        = 20
BB_STD           = 2.0
MA_FAST          = 20
MA_SLOW          = 50

# ── Bot Loop ────────────────────────────────────────────────────────────────
SCAN_INTERVAL    = 60      # seconds between scans
RUN_ONCE         = False   # True = single scan then exit (for debugging)

# ── Safety guard — refuse to run LIVE unless explicitly confirmed ────────────
def assert_demo_mode():
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode detected. Set ACCOUNT_TYPE=LIVE in .env intentionally "
            "and remove this guard only after full demo validation."
        )
