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

# ── Account Currency FX Rate ───────────────────────────────────────────────────
# Units of account currency per 1 USD.  e.g. 150.0 for JPY, 1.0 for USD.
# Used to convert balance → USD for lot-size calculations.
# Set ACCOUNT_FX_RATE in .env for your broker (check broker's USDJPY rate).
ACCOUNT_FX_RATE = float(os.getenv("ACCOUNT_FX_RATE", "1.0"))

# ── Multi-Symbol Trading ───────────────────────────────────────────────────────
_symbols_raw = os.getenv("MT5_SYMBOLS", os.getenv("MT5_SYMBOL", "GOLD"))
SYMBOLS      = [s.strip() for s in _symbols_raw.split(",") if s.strip()]
SYMBOL       = SYMBOLS[0]

# ── Five-Timeframe System ──────────────────────────────────────────────────────
HTF_TIMEFRAME     = "H4"    # big-picture direction (hard gate)
TREND_TIMEFRAME   = "H1"    # major trend direction
CONFIRM_TIMEFRAME = "M15"   # trend confirmation
ENTRY_TIMEFRAME   = "M5"    # entry signals
TIMING_TIMEFRAME  = "M1"    # final entry timing (short)

HTF_CANDLES     = 250   # needs 200+ for MA200 on H4
TREND_CANDLES   = 250   # needs 200+ for MA200 on H1
CONFIRM_CANDLES = 100
ENTRY_CANDLES   = 100
TIMING_CANDLES  = 100   # M1 bars for MACD + RSI momentum

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

# ── Signal Score Threshold ────────────────────────────────────────────────────
# DATA COLLECTION: 1 — fires on minimal confluence, maximises trade count
# REAL MONEY:      3 — requires H4+M15+RSI+BB all agreeing
MIN_SCORE = 1

# ── Risk Parameters ────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_POSITIONS  = 4
MIN_RR_RATIO   = 2.0

# ── Pyramiding (scaling into winning trades) ───────────────────────────────────
# If an existing trade is already PYRAMID_MIN_R× in profit, the bot adds a
# second smaller position in the same direction on the same symbol.
PYRAMID_ENABLED   = True
PYRAMID_MIN_R     = 1.0    # existing trade must be >= 1R in profit to pyramid
PYRAMID_LOT_RATIO = 0.5    # pyramid lot = 50% of a normal-sized trade
PYRAMID_MAX_ADDS  = 1      # max 1 add-on per original position

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

# ── News Filter ────────────────────────────────────────────────────────────────
# Blocks new entries around scheduled high-impact events (NFP, CPI, etc.)
# and when ATR spikes abnormally (unscheduled news / surprise data).
NEWS_FILTER_ENABLED    = True
NEWS_BUFFER_BEFORE_MIN = 30    # minutes to block BEFORE a known event
NEWS_BUFFER_AFTER_MIN  = 30    # minutes to block AFTER a known event
NEWS_ATR_SPIKE_MULT    = 2.0   # block if current ATR > 2× its 20-bar average
# To add custom blackout windows (e.g. FOMC dates), set in .env:
#   NEWS_BLACKOUT=FOMC 2026-06-11 19:00, PCE 2026-06-28 13:30

# ── Scan Loop ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 60
RUN_ONCE      = False


# ── Auto-Escalation Thresholds ────────────────────────────────────────────────
# Bot automatically tightens rules as trade count grows.
# Phase 1 (0–199):   data collection — fire on almost anything
# Phase 2 (200–499): transitional   — require moderate confluence
# Phase 3 (500+):    strict         — institutional-grade filters
MODE_PHASE1_TRADES = 0     # skip data-collection phase — go straight to strict
MODE_PHASE2_TRADES = 0     # skip transitional phase — go straight to strict

_PHASE_SETTINGS = {
    # Phase 1: require 2 real signals — eliminates single-indicator noise trades
    # that would pollute the ML training set with garbage patterns.
    # Wide RSI zones and no session/volume filter to still capture variety.
    1: dict(min_score=2, volume_ratio=0.0, rsi_bull=(35, 62), rsi_bear=(38, 65),
            h4_hard_gate=False, sessions={}),
    2: dict(min_score=2, volume_ratio=0.5, rsi_bull=(38, 58), rsi_bear=(42, 62),
            h4_hard_gate=False, sessions={}),
    3: dict(min_score=3, volume_ratio=0.8, rsi_bull=(40, 55), rsi_bear=(45, 60),
            h4_hard_gate=True,
            sessions={"Tokyo": (0, 2), "London": (7, 16), "NewYork": (13, 21)}),
}

# Runtime mutable — updated by apply_trading_phase()
H4_HARD_GATE = False   # False = soft (data collection), True = hard block


def get_trading_phase(closed_trade_count: int) -> int:
    if closed_trade_count >= MODE_PHASE2_TRADES:
        return 3
    if closed_trade_count >= MODE_PHASE1_TRADES:
        return 2
    return 1


def apply_trading_phase(closed_trade_count: int) -> int:
    """Apply the correct rule set for the current trade count. Returns phase number."""
    global MIN_SCORE, VOLUME_MIN_RATIO, RSI_BULL_MIN, RSI_BULL_MAX
    global RSI_BEAR_MIN, RSI_BEAR_MAX, H4_HARD_GATE, SESSIONS

    phase    = get_trading_phase(closed_trade_count)
    settings = _PHASE_SETTINGS[phase]

    MIN_SCORE        = settings["min_score"]
    VOLUME_MIN_RATIO = settings["volume_ratio"]
    RSI_BULL_MIN, RSI_BULL_MAX = settings["rsi_bull"]
    RSI_BEAR_MIN, RSI_BEAR_MAX = settings["rsi_bear"]
    H4_HARD_GATE     = settings["h4_hard_gate"]
    SESSIONS         = settings["sessions"]

    return phase


def assert_demo_mode():
    if ACCOUNT_TYPE.upper() == "LIVE":
        raise RuntimeError(
            "LIVE mode is engaged. Remove this guard only after full demo validation."
        )
