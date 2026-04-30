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
MT5_PATH     = os.getenv("MT5_PATH",         "")
MAGIC        = int(os.getenv("MT5_MAGIC",    "20240101"))
SLIPPAGE     = int(os.getenv("MT5_SLIPPAGE", "20"))
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE",     "DEMO")

# ── Multi-Symbol Trading ───────────────────────────────────────────────────────
# Comma-separated list: MT5_SYMBOLS=GOLD,#USSPX500,#US100_M26,#Japan225
# Falls back to legacy MT5_SYMBOL for single-symbol setups
_symbols_raw = os.getenv("MT5_SYMBOLS", os.getenv("MT5_SYMBOL", "GOLD"))
SYMBOLS      = [s.strip() for s in _symbols_raw.split(",") if s.strip()]
SYMBOL       = SYMBOLS[0]   # primary symbol (kept for backward compatibility)

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01   # 1 % risk per trade  (applied per symbol)
MAX_DAILY_LOSS = 0.03   # 3 % daily equity drawdown → circuit-breaker
MAX_POSITIONS  = 4      # max concurrent positions across ALL symbols combined
MIN_RR_RATIO   = 2.0    # minimum reward-to-risk before entry

# ── ATR Stop Architecture ──────────────────────────────────────────────────────
ATR_PERIOD  = 14
ATR_SL_MULT = 1.5       # stop-loss   = 1.5 × ATR
ATR_TP_MULT = 3.0       # take-profit = 3.0 × ATR  → 2 : 1 R:R guaranteed

# ── Timeframes ─────────────────────────────────────────────────────────────────
TREND_TIMEFRAME = "M15"
ENTRY_TIMEFRAME = "M1"
TREND_CANDLES   = 200
ENTRY_CANDLES   = 100

# ── Scan Loop ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 60      # seconds between full multi-symbol scans
RUN_ONCE      = False


def assert_demo_mode():
    """Hard guard — prevents accidental live execution during development."""
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode is engaged. Remove this guard only after full demo validation."
        )
