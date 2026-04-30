"""
Central configuration — all tunables live here, secrets in .env

Current mode: DATA COLLECTION — relaxed filters for demo data gathering.
When switching to real money, restore the values marked # REAL MONEY below.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── MT5 Connection ─────────────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN",    "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD",     "")
MT5_SERVER   = os.getenv("MT5_SERVER",       "")
MT5_PATH     = os.getenv("MT5_PATH",         "")
MAGIC        = int(os.getenv("MT5_MAGIC",    "20240101"))
SLIPPAGE     = int(os.getenv("MT5_SLIPPAGE", "20"))
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE",     "DEMO")

# ── Multi-Symbol Trading ───────────────────────────────────────────────────────
_symbols_raw = os.getenv("MT5_SYMBOLS", os.getenv("MT5_SYMBOL", "GOLD"))
SYMBOLS      = [s.strip() for s in _symbols_raw.split(",") if s.strip()]
SYMBOL       = SYMBOLS[0]

# ── Three-Timeframe System ─────────────────────────────────────────────────────
TREND_TIMEFRAME   = "H1"    # major trend direction
CONFIRM_TIMEFRAME = "M15"   # trend confirmation
ENTRY_TIMEFRAME   = "M5"    # entry signals

TREND_CANDLES   = 100
CONFIRM_CANDLES = 100
ENTRY_CANDLES   = 100

# ── RSI Pullback Zones ─────────────────────────────────────────────────────────
# DATA COLLECTION — wider zones, more candles qualify
RSI_BULL_MIN = 35   # REAL MONEY: 40
RSI_BULL_MAX = 60   # REAL MONEY: 55
RSI_BEAR_MIN = 40   # REAL MONEY: 45
RSI_BEAR_MAX = 65   # REAL MONEY: 60

# ── Session Filter — all times UTC ────────────────────────────────────────────
# DATA COLLECTION — empty = trade 24/5, no dead zones
# REAL MONEY: restore the dict below
#   SESSIONS = {
#       "Tokyo":   (0,  2),
#       "London":  (7,  16),
#       "NewYork": (13, 21),
#   }
SESSIONS = {}

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_POSITIONS  = 4
MIN_RR_RATIO   = 2.0

# ── Volume Filter ──────────────────────────────────────────────────────────────
# DATA COLLECTION — 50% still blocks dead bars, but passes most candles
VOLUME_LOOKBACK  = 20
VOLUME_MIN_RATIO = 0.0   # REAL MONEY: 0.8  (0.0 = disabled for data collection)

# ── ATR Stop Architecture ──────────────────────────────────────────────────────
ATR_PERIOD  = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

# ── Position Management — Trailing Stop + Partial TP ──────────────────────────
BREAKEVEN_AT_R   = 1.0
TRAIL_START_AT_R = 1.5
TRAIL_ATR_MULT   = 0.5
PARTIAL_TP_RATIO = 0.5

# ── Scan Loop ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 60
RUN_ONCE      = False


def assert_demo_mode():
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode is engaged. Remove this guard only after full demo validation."
        )
