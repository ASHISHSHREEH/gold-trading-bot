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
# In a real trend RSI rarely hits 30/70 — use the pullback zone instead
RSI_BULL_MIN = 40   # bull pullback: RSI dipped into 40-55 range
RSI_BULL_MAX = 55
RSI_BEAR_MIN = 45   # bear rally:   RSI bounced into 45-60 range
RSI_BEAR_MAX = 60

# ── Session Filter (Upgrade 3) — all times UTC ────────────────────────────────
# Tokyo open has real volume at the start — user wants to trade it
# London and New York are the institutional sessions for all symbols
SESSIONS = {
    "Tokyo":   (0,  2),    # 00:00–02:00 UTC  (09:00–11:00 JST)
    "London":  (7,  16),   # 07:00–16:00 UTC  (08:00–17:00 BST)
    "NewYork": (13, 21),   # 13:00–21:00 UTC  (09:00–17:00 EDT)
}
# Dead zones where bot sleeps: 02:00–07:00 UTC and 21:00–00:00 UTC

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_POSITIONS  = 4
MIN_RR_RATIO   = 2.0

# ── Volume Filter (Upgrade 5) ──────────────────────────────────────────────────
# Current bar volume must be >= this ratio of the 20-bar average
# Guards against fake moves in low-liquidity periods
VOLUME_LOOKBACK  = 20
VOLUME_MIN_RATIO = 0.8   # 80 % of average = minimum acceptable activity

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
