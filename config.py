"""
Central configuration — all tunables live here, secrets in .env

DATA_COLLECTION_MODE=true  →  relaxed filters for demo data gathering
DATA_COLLECTION_MODE=false →  strict real-money filters (default)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Mode switch ────────────────────────────────────────────────────────────────
DATA_COLLECTION_MODE = os.getenv("DATA_COLLECTION_MODE", "false").lower() == "true"

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
# Upgrade 1: H1 major trend → M15 confirmation → M5 entry (replaced M1)
TREND_TIMEFRAME   = "H1"    # major trend direction
CONFIRM_TIMEFRAME = "M15"   # trend confirmation
ENTRY_TIMEFRAME   = "M5"    # entry signals (clean, not noisy M1)

TREND_CANDLES   = 100       # H1 candles
CONFIRM_CANDLES = 100       # M15 candles
ENTRY_CANDLES   = 100       # M5 candles

# ── RSI Pullback Zones (Upgrade 2) ─────────────────────────────────────────────
# REAL: tight pullback zones — RSI must be mid-trend, not at extremes
# DATA: wider zones so more candles qualify
RSI_BULL_MIN = 35 if DATA_COLLECTION_MODE else 40
RSI_BULL_MAX = 60 if DATA_COLLECTION_MODE else 55
RSI_BEAR_MIN = 40 if DATA_COLLECTION_MODE else 45
RSI_BEAR_MAX = 65 if DATA_COLLECTION_MODE else 60

# ── Session Filter (Upgrade 3) — all times UTC ────────────────────────────────
# REAL: Tokyo open + London + New York only
# DATA: empty dict = trade 24/5, no dead zones
SESSIONS = {} if DATA_COLLECTION_MODE else {
    "Tokyo":   (0,  2),    # 00:00–02:00 UTC  (09:00–11:00 JST)
    "London":  (7,  16),   # 07:00–16:00 UTC  (08:00–17:00 BST)
    "NewYork": (13, 21),   # 13:00–21:00 UTC  (09:00–17:00 EDT)
}

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_POSITIONS  = 4
MIN_RR_RATIO   = 2.0

# ── Volume Filter (Upgrade 5) ──────────────────────────────────────────────────
# REAL: 80 % of avg — guards against fake moves in thin markets
# DATA: 50 % — still blocks near-zero volume bars, but passes most candles
VOLUME_LOOKBACK  = 20
VOLUME_MIN_RATIO = 0.5 if DATA_COLLECTION_MODE else 0.8

# ── ATR Stop Architecture ──────────────────────────────────────────────────────
ATR_PERIOD  = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

# ── Position Management — Trailing Stop + Partial TP (Upgrade 4) ──────────────
BREAKEVEN_AT_R   = 1.0   # move SL to breakeven when unrealised = 1R
TRAIL_START_AT_R = 1.5   # start trailing when unrealised = 1.5R
TRAIL_ATR_MULT   = 0.5   # trail distance = 0.5 × ATR
PARTIAL_TP_RATIO = 0.5   # close this fraction of position at 1R

# ── Scan Loop ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 60
RUN_ONCE      = False


def assert_demo_mode():
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode is engaged. Remove this guard only after full demo validation."
        )
