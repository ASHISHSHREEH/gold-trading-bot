"""
Central configuration — all tunables live here, secrets in .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── MT5 Connection ─────────────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN",    "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD",     "")
MT5_SERVER   = os.getenv("MT5_SERVER",       "")
SYMBOL       = os.getenv("MT5_SYMBOL",       "XAUUSD")
MAGIC        = int(os.getenv("MT5_MAGIC",    "20240101"))
SLIPPAGE     = int(os.getenv("MT5_SLIPPAGE", "20"))
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE",     "DEMO")

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01   # 1 % risk per trade
MAX_DAILY_LOSS = 0.03   # 3 % daily equity drawdown → circuit-breaker
MAX_POSITIONS  = 3      # max concurrent open trades
MIN_RR_RATIO   = 2.0    # minimum reward-to-risk before entry is allowed

# ── ATR Stop Architecture ──────────────────────────────────────────────────────
ATR_PERIOD  = 14
ATR_SL_MULT = 1.5       # stop-loss  = 1.5 × ATR  (Wilder standard)
ATR_TP_MULT = 3.0       # take-profit = 3.0 × ATR  → guaranteed 2 : 1 R:R

# ── Timeframes ─────────────────────────────────────────────────────────────────
TREND_TIMEFRAME = "M15"
ENTRY_TIMEFRAME = "M1"
TREND_CANDLES   = 200   # history depth for trend analysis
ENTRY_CANDLES   = 100   # history depth for entry signals

# ── Scan Loop ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 60      # seconds between scans
RUN_ONCE      = False   # True → single scan then exit (useful for debugging)


def assert_demo_mode():
    """Hard guard — prevents accidental live execution during development."""
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode is engaged. Remove this guard only after full demo validation."
        )
