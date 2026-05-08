"""
GOLD TRADING BOT — MT5 MULTI-SYMBOL LIVE EDITION  (v2.0)
=========================================================
Five upgrades over v1:
  1. Three-timeframe: H1 trend → M15 confirm → M5 entry  (replaced M1)
  2. RSI pullback zones instead of oversold/overbought extremes
     Bull: 40–55  /  Bear: 45–60
  3. Session filter — Tokyo 00:00-02:00, London 07:00-16:00, NY 13:00-21:00 UTC
     (bot sleeps 02:00–07:00 and 21:00–00:00 UTC; still manages open positions)
  4. Partial TP: close 50 % at 1R, move SL to breakeven, trail at 0.5×ATR from 1.5R
  5. Volume gate: current M5 bar volume ≥ 80 % of 20-bar average (hard gate)

Symbols: GOLD, #USSPX500, #US100_M26, #Japan225  (FxPro Demo, JPY account)

Prerequisites:
    pip install -r requirements.txt
    MT5_SYMBOLS=GOLD,#USSPX500,#US100_M26,#Japan225  in .env
"""

import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import config

config.assert_demo_mode()

from data.mt5_fetcher             import MT5DataFetcher
from indicators.atr               import ATRCalculator
from indicators.rsi               import RSICalculator
from indicators.macd              import MACDCalculator
from indicators.bollinger         import BollingerBandsCalculator
from indicators.moving_average    import MovingAverageCalculator
from trading.mt5_executor         import MT5Executor
from trading.mt5_position_manager import MT5PositionManager
from database.trade_logger        import TradeLogger
from learning.learning_engine     import LearningEngine

# ── Logging ────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/mt5_bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("GoldBot-MT5")
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ── Shared indicator instances (stateless) ─────────────────────────────────────
_IND = {
    "atr":  ATRCalculator(period=config.ATR_PERIOD),
    "rsi":  RSICalculator(period=14),
    "macd": MACDCalculator(),
    "bb":   BollingerBandsCalculator(period=20, std_dev=2),
    "ma":   MovingAverageCalculator(),
}
_MA_PERIODS_TREND = [50, 200]   # H1 — slow, reliable trend filter
_MA_PERIODS_ENTRY = [20, 50]    # M15/M5 — faster, for confirmation

_SYMBOL_LABELS = {
    "GOLD":       "Gold   (XAU)",
    "#USSPX500":  "S&P500 (US)",
    "#US100_M26": "NASDAQ (US)",
    "#Japan225":  "Nikkei (JP)",
}

# ── Per-position management state ──────────────────────────────────────────────
# ticket → {symbol, direction, entry_price, initial_sl, atr,
#           partial_done, breakeven_done, trail_sl,
#           market_snapshot (for RL update on close)}
_pos_state: Dict[int, Dict[str, Any]] = {}

# ── AI Learning Engine (singleton, initialised in main()) ──────────────────────
_ai_engine: Optional[LearningEngine] = None


# ── Session filter (Upgrade 3) ─────────────────────────────────────────────────

def current_session() -> Optional[str]:
    """Return active session name, or None in a dead zone.
    Empty SESSIONS dict means trade 24/5 — returns 'Always'."""
    if not config.SESSIONS:
        return "Always"
    utc_hour = datetime.now(timezone.utc).hour
    for name, (start, end) in config.SESSIONS.items():
        if start <= utc_hour < end:
            return name
    return None


def is_trading_session() -> bool:
    return current_session() is not None


# ── Four-timeframe analysis ────────────────────────────────────────────────────

def analyse_htf(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    """H4: big-picture direction via MA50/MA200 — acts as a hard gate."""
    df = fetcher.get_historical_data(config.HTF_TIMEFRAME, config.HTF_CANDLES, symbol)
    if df.empty or len(df) < _MA_PERIODS_TREND[-1] + 5:
        logger.warning(f"[{symbol}] Insufficient H4 data.")
        return None

    ma_df = _IND["ma"].calculate_multiple_mas(df["close"], periods=_MA_PERIODS_TREND)
    ana   = _IND["ma"].analyze_latest(df["close"].iloc[:-1], ma_df.iloc[:-1])

    return {
        "timeframe": config.HTF_TIMEFRAME,
        "price":     float(df["close"].iloc[-2]),
        "ma_fast":   ana["ma_fast"],
        "ma_slow":   ana["ma_slow"],
        "trend":     ana["trend"],
    }


def analyse_trend(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    """H1: establish major trend direction via MA50/MA200 crossover."""
    df = fetcher.get_historical_data(config.TREND_TIMEFRAME, config.TREND_CANDLES, symbol)
    if df.empty or len(df) < _MA_PERIODS_TREND[-1] + 5:
        logger.warning(f"[{symbol}] Insufficient H1 data.")
        return None

    ma_df = _IND["ma"].calculate_multiple_mas(df["close"], periods=_MA_PERIODS_TREND)
    df    = df.join(ma_df)
    ana   = _IND["ma"].analyze_latest(df["close"].iloc[:-1], ma_df.iloc[:-1])

    return {
        "timeframe": config.TREND_TIMEFRAME,
        "price":     float(df["close"].iloc[-2]),
        "timestamp": df.index[-2],
        "ma_fast":   ana["ma_fast"],
        "ma_slow":   ana["ma_slow"],
        "trend":     ana["trend"],
    }


def analyse_confirm(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    """M15: confirm the H1 trend via MA structure + MACD direction."""
    df = fetcher.get_historical_data(config.CONFIRM_TIMEFRAME, config.CONFIRM_CANDLES, symbol)
    if df.empty or len(df) < 60:
        logger.warning(f"[{symbol}] Insufficient M15 data.")
        return None

    ma_df   = _IND["ma"].calculate_multiple_mas(df["close"], periods=_MA_PERIODS_ENTRY)
    df      = df.join(ma_df)
    macd_df = _IND["macd"].calculate_macd(df)
    df      = df.join(macd_df)

    ma_ana   = _IND["ma"].analyze_latest(df["close"].iloc[:-1], ma_df.iloc[:-1])
    macd_ana = _IND["macd"].analyze_latest(macd_df)

    return {
        "timeframe": config.CONFIRM_TIMEFRAME,
        "price":     float(df["close"].iloc[-2]),
        "timestamp": df.index[-2],
        "ma_trend":  ma_ana["trend"],
        "ma_fast":   ma_ana["ma_fast"],
        "ma_slow":   ma_ana["ma_slow"],
        "macd":      macd_ana["signal"],
    }


def analyse_entry(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    """M5: RSI pullback zone + BB position + volume gate (Upgrade 2, 5) + ATR."""
    candles = max(config.ENTRY_CANDLES, config.VOLUME_LOOKBACK + 5)
    df = fetcher.get_historical_data(config.ENTRY_TIMEFRAME, candles, symbol)
    if df.empty or len(df) < 30:
        logger.warning(f"[{symbol}] Insufficient M5 data.")
        return None

    df["rsi"] = _IND["rsi"].calculate_rsi(df)
    bb_df     = _IND["bb"].calculate_bands(df["close"])
    df        = df.join(bb_df)
    atr_val   = _IND["atr"].get_latest(df)

    rsi_val = float(df["rsi"].iloc[-1]) if not df["rsi"].isna().iloc[-1] else None
    bb_ana  = _IND["bb"].analyze_latest(df["close"], bb_df)

    # Volume gate (Upgrade 5) — prefer tick_volume, fall back to volume column
    vol_col   = "tick_volume" if "tick_volume" in df.columns else "volume"
    volume_ok = False
    if vol_col in df.columns and len(df) >= config.VOLUME_LOOKBACK + 1:
        avg_vol   = float(df[vol_col].iloc[-(config.VOLUME_LOOKBACK + 1):-1].mean())
        cur_vol   = float(df[vol_col].iloc[-1])
        volume_ok = avg_vol > 0 and (cur_vol / avg_vol) >= config.VOLUME_MIN_RATIO

    return {
        "timeframe": config.ENTRY_TIMEFRAME,
        "price":     float(df["close"].iloc[-1]),
        "timestamp": df.index[-1],
        "atr":       atr_val,
        "rsi":       rsi_val,
        "bb":        bb_ana,
        "volume_ok": volume_ok,
    }


def analyse_timing(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    """M1: final entry timing — MACD momentum + RSI direction."""
    df = fetcher.get_historical_data(config.TIMING_TIMEFRAME, config.TIMING_CANDLES, symbol)
    if df.empty or len(df) < 40:
        logger.warning(f"[{symbol}] Insufficient M1 data.")
        return None

    macd_df  = _IND["macd"].calculate_macd(df)
    macd_ana = _IND["macd"].analyze_latest(macd_df)
    rsi_s    = _IND["rsi"].calculate_rsi(df)
    rsi_val  = float(rsi_s.iloc[-1]) if not rsi_s.isna().iloc[-1] else None

    # Combine MACD + RSI midline (50) for M1 momentum direction
    macd_bull = macd_ana["signal"] in ("BUY",)
    macd_bear = macd_ana["signal"] in ("SELL",)
    rsi_bull  = rsi_val is not None and rsi_val > 50
    rsi_bear  = rsi_val is not None and rsi_val < 50

    if macd_bull and rsi_bull:
        direction = "BULL"
    elif macd_bear and rsi_bear:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    return {
        "timeframe": config.TIMING_TIMEFRAME,
        "macd":      macd_ana["signal"],
        "rsi":       round(rsi_val, 1) if rsi_val is not None else None,
        "direction": direction,
    }


# ── Signal generation ──────────────────────────────────────────────────────────

def _rsi_in_bull_zone(rsi: Optional[float]) -> bool:
    if rsi is None:
        return False
    return config.RSI_BULL_MIN <= rsi <= config.RSI_BULL_MAX


def _rsi_in_bear_zone(rsi: Optional[float]) -> bool:
    if rsi is None:
        return False
    return config.RSI_BEAR_MIN <= rsi <= config.RSI_BEAR_MAX


def _confirm_agrees(confirm: Dict, h1_trend: str) -> bool:
    """True when at least one M15 indicator (MA or MACD) aligns with H1 direction."""
    is_bull  = h1_trend in ("STRONG_BULL", "BULL")
    is_bear  = h1_trend in ("STRONG_BEAR", "BEAR")
    ma_bull  = confirm["ma_trend"] in ("STRONG_BULL", "BULL")
    ma_bear  = confirm["ma_trend"] in ("STRONG_BEAR", "BEAR")
    if is_bull:
        return ma_bull or confirm["macd"] == "BUY"
    if is_bear:
        return ma_bear or confirm["macd"] == "SELL"
    return False


def generate_signal(
    htf:     Dict,
    trend:   Dict,
    confirm: Dict,
    entry:   Dict,
    timing:  Dict,
) -> Dict[str, Any]:
    htf_dir   = htf["trend"]
    trend_dir = trend["trend"]
    is_bull   = trend_dir in ("STRONG_BULL", "BULL")
    is_bear   = trend_dir in ("STRONG_BEAR", "BEAR")
    htf_bull  = htf_dir in ("STRONG_BULL", "BULL")
    htf_bear  = htf_dir in ("STRONG_BEAR", "BEAR")
    rsi       = entry["rsi"]
    bb        = entry["bb"]
    reasons   = [f"H4: {htf_dir}", f"H1: {trend_dir}"]
    score     = 0

    # ── H4 gate — auto-switched by apply_trading_phase() ─────────────────────
    if (is_bull and htf_bear) or (is_bear and htf_bull):
        if config.H4_HARD_GATE:
            reasons.append(f"BLOCKED: H4 {htf_dir} conflicts with H1 {trend_dir}")
            return {
                "signal": "NEUTRAL", "confidence": "LOW", "score": 0,
                "reasons": reasons, "htf": htf_dir, "trend": trend_dir,
                "rsi": rsi, "macd": confirm["macd"],
                "bb": bb["position"], "volume_ok": entry["volume_ok"],
            }
        reasons.append(f"H4 {htf_dir} conflicts with H1 {trend_dir} — no H4 bonus")

    # ── Volume hard gate ───────────────────────────────────────────────────────
    if not entry["volume_ok"]:
        reasons.append(f"BLOCKED: M5 volume below {config.VOLUME_MIN_RATIO*100:.0f}% of {config.VOLUME_LOOKBACK}-bar avg")
        return {
            "signal": "NEUTRAL", "confidence": "LOW", "score": 0,
            "reasons": reasons, "htf": htf_dir, "trend": trend_dir,
            "rsi": rsi, "macd": confirm["macd"],
            "bb": bb["position"], "volume_ok": False,
        }

    signal = "NEUTRAL"

    # DATA COLLECTION: also trade when H1 is NEUTRAL but H4 has clear direction
    if not (is_bull or is_bear):
        if htf_bull:
            is_bull   = True
            trend_dir = "BULL"
            reasons.append(f"H1 NEUTRAL — using H4 {htf_dir} as direction")
        elif htf_bear:
            is_bear   = True
            trend_dir = "BEAR"
            reasons.append(f"H1 NEUTRAL — using H4 {htf_dir} as direction")

    if is_bull or is_bear:
        # H4 actively confirms H1 → bonus point
        if (is_bull and htf_bull) or (is_bear and htf_bear):
            score += 1
            reasons.append(f"H4 confirms {htf_dir}")

        # M15 confirmation
        if _confirm_agrees(confirm, trend_dir):
            score += 1
            reasons.append(
                f"M15 confirms ({confirm['ma_trend']}, MACD={confirm['macd']})"
            )
        else:
            reasons.append(
                f"M15 diverges ({confirm['ma_trend']}, MACD={confirm['macd']})"
            )

        if is_bull:
            if _rsi_in_bull_zone(rsi):
                score += 1
                rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
                reasons.append(
                    f"RSI pullback {rsi_str} in [{config.RSI_BULL_MIN}–{config.RSI_BULL_MAX}]"
                )
            if bb["position"] in ("NEAR_LOWER", "BELOW_LOWER", "WALKING_UP"):
                score += 1
                reasons.append(f"BB {bb['position']}")
            signal = "BUY" if score >= config.MIN_SCORE else "NEUTRAL"

        else:  # is_bear
            if _rsi_in_bear_zone(rsi):
                score += 1
                rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
                reasons.append(
                    f"RSI rally {rsi_str} in [{config.RSI_BEAR_MIN}–{config.RSI_BEAR_MAX}]"
                )
            if bb["position"] in ("NEAR_UPPER", "ABOVE_UPPER", "WALKING_DOWN"):
                score += 1
                reasons.append(f"BB {bb['position']}")
            signal = "SELL" if score >= config.MIN_SCORE else "NEUTRAL"

    else:
        reasons.append("No clear H1 or H4 trend — standing aside")

    # M1 timing confirmation — adds +1 if momentum agrees
    if signal != "NEUTRAL":
        t_dir = timing["direction"]
        rsi_str = f"{timing['rsi']}" if timing["rsi"] is not None else "N/A"
        if (signal == "BUY"  and t_dir == "BULL") or \
           (signal == "SELL" and t_dir == "BEAR"):
            score += 1
            reasons.append(
                f"M1 timing {t_dir} (MACD={timing['macd']} RSI={rsi_str})"
            )
        else:
            reasons.append(
                f"M1 timing {t_dir} (MACD={timing['macd']} RSI={rsi_str})"
            )

    confidence = "HIGH" if score >= 4 else ("MODERATE" if score >= 2 else "LOW")

    return {
        "signal":     signal,
        "confidence": confidence,
        "score":      score,
        "reasons":    reasons,
        "htf":        htf_dir,
        "trend":      trend_dir,
        "rsi":        rsi,
        "macd":       confirm["macd"],
        "bb":         bb["position"],
        "volume_ok":  entry["volume_ok"],
        "m1":         timing["direction"],
    }


# ── Position management: partial TP + trailing stop (Upgrade 4) ───────────────

def manage_open_positions(
    positions: List[Dict],
    fetcher:   MT5DataFetcher,
    executor:  MT5Executor,
) -> None:
    """
    For every open position:
    - At 1R unrealised: partial close PARTIAL_TP_RATIO + move SL to breakeven
    - At TRAIL_START_AT_R+: trail SL at current_price ∓ TRAIL_ATR_MULT×ATR
    Called every scan cycle regardless of session so management never pauses.
    """
    _atr_cache: Dict[str, float] = {}

    for pos in positions:
        ticket    = pos["ticket"]
        symbol    = pos["symbol"]
        direction = pos["direction"]
        entry     = pos["entry_price"]
        current   = pos["current_price"]
        cur_sl    = pos["sl"]
        cur_tp    = pos["tp"]

        # Initialise state for positions we pick up after a restart
        if ticket not in _pos_state:
            _pos_state[ticket] = {
                "symbol":         symbol,
                "direction":      direction,
                "entry_price":    entry,
                "initial_sl":     cur_sl,
                "atr":            None,
                "partial_done":   False,
                "breakeven_done": False,
                "trail_sl":       cur_sl,
            }
            logger.info(
                f"[{symbol}] Tracking ticket={ticket} {direction} "
                f"@ {entry} SL={cur_sl}"
            )

        state = _pos_state[ticket]

        # Fetch current ATR, cached per symbol per cycle
        if symbol not in _atr_cache:
            df = fetcher.get_historical_data(
                config.ENTRY_TIMEFRAME, config.ENTRY_CANDLES, symbol
            )
            _atr_cache[symbol] = _IND["atr"].get_latest(df) if not df.empty else None
        atr = _atr_cache[symbol]
        if state["atr"] is None and atr:
            state["atr"] = atr
        live_atr = atr or state["atr"]

        risk = abs(entry - state["initial_sl"])
        if risk == 0:
            continue

        move = current - entry if direction == "BUY" else entry - current
        r    = move / risk

        # ── 1R: partial close (Upgrade 4) ─────────────────────────────────────
        if r >= config.BREAKEVEN_AT_R and not state["partial_done"]:
            if executor.partial_close(ticket, symbol, config.PARTIAL_TP_RATIO):
                state["partial_done"] = True
                logger.info(
                    f"[{symbol}] ticket={ticket} partial close "
                    f"{config.PARTIAL_TP_RATIO:.0%} at {r:.2f}R"
                )

        # ── 1R: move SL to breakeven (Upgrade 4) ──────────────────────────────
        if r >= config.BREAKEVEN_AT_R and not state["breakeven_done"]:
            be_sl = entry
            moved = False
            if direction == "BUY" and be_sl > cur_sl:
                moved = executor.modify_position_sl(ticket, symbol, be_sl, cur_tp)
            elif direction == "SELL" and be_sl < cur_sl:
                moved = executor.modify_position_sl(ticket, symbol, be_sl, cur_tp)
            if moved:
                state["breakeven_done"] = True
                state["trail_sl"]       = be_sl
                logger.info(
                    f"[{symbol}] ticket={ticket} SL → breakeven {be_sl:.5f}"
                )

        # ── 1.5R+: trailing stop (Upgrade 4) ──────────────────────────────────
        if r >= config.TRAIL_START_AT_R and live_atr:
            trail_dist = live_atr * config.TRAIL_ATR_MULT
            if direction == "BUY":
                new_trail = current - trail_dist
                # Advance only — never pull the trail back
                if new_trail > state["trail_sl"]:
                    if executor.modify_position_sl(ticket, symbol, new_trail, cur_tp):
                        state["trail_sl"] = new_trail
                        logger.info(
                            f"[{symbol}] ticket={ticket} trail SL → "
                            f"{new_trail:.5f} (R={r:.2f})"
                        )
            else:  # SELL
                new_trail = current + trail_dist
                if new_trail < state["trail_sl"]:
                    if executor.modify_position_sl(ticket, symbol, new_trail, cur_tp):
                        state["trail_sl"] = new_trail
                        logger.info(
                            f"[{symbol}] ticket={ticket} trail SL → "
                            f"{new_trail:.5f} (R={r:.2f})"
                        )

    # Purge state for positions that are no longer open
    open_tickets = {p["ticket"] for p in positions}
    for ticket in [t for t in list(_pos_state) if t not in open_tickets]:
        logger.info(f"Position ticket={ticket} closed — removing state.")
        del _pos_state[ticket]


# ── Display helpers ────────────────────────────────────────────────────────────

def _line(char="─", w=70):
    print(char * w)


def display_header(scan: int, session: Optional[str]):
    _line("═")
    sess_label = (
        f"Session: {session}"
        if session
        else "Session: DEAD ZONE (skipping new entries)"
    )
    if config.MIN_SCORE == 1:
        phase_label = "PHASE 1 — Data Collection"
    elif config.MIN_SCORE == 2:
        phase_label = "PHASE 2 — Transitional"
    else:
        phase_label = "PHASE 3 — Strict"
    print(
        f"  SCAN #{scan}  |  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  |  "
        f"{sess_label}  |  {phase_label}  |  Score≥{config.MIN_SCORE}  |  "
        f"Symbols: {', '.join(config.SYMBOLS)}"
    )
    _line("═")


def display_account(acct: Dict):
    if not acct:
        return
    print(
        f"  ACCOUNT  Balance: {acct['balance']:,.2f} {acct['currency']}  |  "
        f"Equity: {acct['equity']:,.2f}  |  "
        f"Free Margin: {acct['free_margin']:,.2f}  |  "
        f"Leverage: 1:{acct['leverage']}"
    )


def display_positions(positions: List[Dict]):
    _line()
    print(f"  OPEN POSITIONS  ({len(positions)}/{config.MAX_POSITIONS})")
    if not positions:
        print("  No open positions.")
        return
    for p in positions:
        sign  = "+" if p["profit"] >= 0 else ""
        label = _SYMBOL_LABELS.get(p["symbol"], p["symbol"])
        state = _pos_state.get(p["ticket"], {})
        flags = []
        if state.get("partial_done"):   flags.append("partial✓")
        if state.get("breakeven_done"): flags.append("BE✓")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"    #{p['ticket']}  {label}  {p['direction']:<4}  "
            f"entry={p['entry_price']:.2f}  now={p['current_price']:.2f}  "
            f"SL={p['sl']:.2f}  TP={p['tp']:.2f}  "
            f"P&L={sign}{p['profit']:.2f}{flag_str}"
        )


def display_symbol_analysis(
    symbol:      str,
    signal_data: Dict,
    htf:         Dict,
    trend:       Dict,
    confirm:     Dict,
    entry:       Dict,
    timing:      Dict,
):
    label    = _SYMBOL_LABELS.get(symbol, symbol)
    sig      = signal_data["signal"]
    icon     = {"BUY": "▲ BUY", "SELL": "▼ SELL", "NEUTRAL": "● NEUTRAL"}[sig]
    rsi_str  = f"{entry['rsi']:.1f}" if entry["rsi"] is not None else "N/A"
    m1_rsi   = f"{timing['rsi']}" if timing["rsi"] is not None else "N/A"
    vol_flag = "✓" if entry["volume_ok"] else "✗"

    _line()
    print(f"  [{label}]")
    print(
        f"  H4  Bias   : {htf['trend']:<14}  "
        f"MA50={htf['ma_fast']:.2f}  MA200={htf['ma_slow']:.2f}"
    )
    print(
        f"  H1  Trend  : {trend['trend']:<14}  "
        f"MA50={trend['ma_fast']:.2f}  MA200={trend['ma_slow']:.2f}"
    )
    print(
        f"  M15 Confirm: {confirm['ma_trend']:<14}  "
        f"MACD={confirm['macd']}"
    )
    print(
        f"  M5  Entry  : price={entry['price']:.2f}  ATR={entry['atr']:.4f}  "
        f"RSI={rsi_str}  BB={entry['bb']['position']}  Vol={vol_flag}"
    )
    print(
        f"  M1  Timing : {timing['direction']:<14}  "
        f"MACD={timing['macd']}  RSI={m1_rsi}"
    )
    print(
        f"  {icon}  |  Score: {signal_data['score']}/5  |  "
        f"{signal_data['confidence']}  |  "
        f"{'; '.join(signal_data['reasons'])}"
    )


def display_execution(symbol: str, execution: Dict):
    label = _SYMBOL_LABELS.get(symbol, symbol)
    _line()
    print(
        f"  EXECUTED [{label}]  {execution['direction']}  "
        f"ticket={execution['ticket']}  @ {execution['entry_price']:.2f}  "
        f"vol={execution['volume']} lots"
    )
    print(
        f"  SL={execution['stop_loss']:.2f}  TP={execution['take_profit']:.2f}  "
        f"ATR={execution['atr']:.4f}  R:R={execution['rr_ratio']:.2f}  "
        f"Risk={execution['risk_amount']:.2f}"
    )


def display_ai_decision(decision) -> None:
    """Print AI layer voting summary beneath signal analysis."""
    if decision is None:
        return
    d = decision.to_dict() if hasattr(decision, "to_dict") else decision
    ml_str   = f"{d['ml_score']:.2f}" if d.get("ml_active") else "N/A"
    veto_str = f"  ⚑ VETO: {d['veto_reason']}" if d.get("veto_reason") else ""
    print(
        f"  AI  │ score={d['base_score']:.1f}  ml={ml_str}"
        f"  rl={d['rl_vote']}  conf={d['ai_confidence']:.1f}/10"
        f"  → {d['decision']}{veto_str}"
    )


def display_stats(stats: Dict):
    if not stats or not stats.get("total_trades"):
        return
    _line()
    print(
        f"  SESSION  Trades: {stats['total_trades']}  |  "
        f"Win rate: {stats['win_rate']:.1f}%  |  "
        f"P-factor: {stats['profit_factor']:.2f}  |  "
        f"Net P&L: {stats.get('total_profit', 0):.2f}"
    )


# ── Per-symbol scan ────────────────────────────────────────────────────────────

def scan_symbol(
    symbol:    str,
    fetcher:   MT5DataFetcher,
    executor:  MT5Executor,
    pos_mgr:   MT5PositionManager,
    logger_db: TradeLogger,
    session:   Optional[str] = None,
) -> None:
    htf     = analyse_htf(fetcher, symbol)
    trend   = analyse_trend(fetcher, symbol)
    confirm = analyse_confirm(fetcher, symbol)
    entry   = analyse_entry(fetcher, symbol)
    timing  = analyse_timing(fetcher, symbol)

    if htf is None or trend is None or confirm is None or entry is None or timing is None:
        print(f"  [{symbol}] Data unavailable — skipping.")
        return

    signal_data = generate_signal(htf, trend, confirm, entry, timing)
    display_symbol_analysis(symbol, signal_data, htf, trend, confirm, entry, timing)
    logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="PENDING")

    risk = pos_mgr.check_risk_limits(symbol=symbol)
    if not risk["can_open_new"]:
        print(f"  GATE: {'; '.join(risk['reasons'])}")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="BLOCKED")
        return

    if signal_data["signal"] == "NEUTRAL":
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="NEUTRAL")
        return

    # ── AI layer vote ──────────────────────────────────────────────────────────
    ai_decision = None
    if _ai_engine is not None:
        try:
            ai_decision = _ai_engine.ai_vote(
                signal_data, entry, htf, trend, confirm, timing, session
            )
            display_ai_decision(ai_decision)
            if ai_decision.decision == "NEUTRAL":
                logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="AI_VETO")
                return
        except Exception as exc:
            logger.error("[%s] AI vote error — proceeding without AI: %s", symbol, exc)

    execution = executor.execute_signal(
        signal    = signal_data["signal"],
        atr_value = entry["atr"],
        symbol    = symbol,
    )

    if execution:
        display_execution(symbol, execution)
        logger_db.log_trade_open(execution)
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="EXECUTED")

        # ── Store ML features for future training ──────────────────────────────
        from datetime import datetime, timezone
        ml_features = {
            "symbol":       symbol,
            "direction":    execution["direction"],
            "htf_trend":    htf.get("trend"),
            "h1_trend":     trend.get("trend"),
            "m15_trend":    confirm.get("ma_trend"),
            "m1_direction": timing.get("direction"),
            "rsi":          entry.get("rsi"),
            "macd_signal":  confirm.get("macd"),
            "bb_position":  (entry.get("bb") or {}).get("position"),
            "atr":          entry.get("atr"),
            "spread":       entry.get("spread"),
            "volume_ratio": entry.get("volume_ratio"),
            "base_score":   signal_data.get("score", 0),
            "session_hour": datetime.now(timezone.utc).hour,
            "ml_score":     ai_decision.ml_score   if ai_decision else None,
            "rl_vote":      ai_decision.rl_vote     if ai_decision else None,
            "ai_confidence": ai_decision.ai_confidence if ai_decision else None,
            "ai_decision":  ai_decision.decision    if ai_decision else None,
        }
        logger_db.log_learning_features(execution["ticket"], ml_features)

        # ── Register position state (includes market snapshot for RL) ──────────
        market_snapshot = {
            "h1_trend": trend.get("trend", "NEUTRAL"),
            "h4_trend": htf.get("trend", "NEUTRAL"),
            "rsi":      entry.get("rsi"),
            "atr":      entry.get("atr"),
            "session":  session,
        }
        _pos_state[execution["ticket"]] = {
            "symbol":          symbol,
            "direction":       execution["direction"],
            "entry_price":     execution["entry_price"],
            "initial_sl":      execution["stop_loss"],
            "atr":             execution["atr"],
            "partial_done":    False,
            "breakeven_done":  False,
            "trail_sl":        execution["stop_loss"],
            "market_snapshot": market_snapshot,
        }
    else:
        print(f"  [{symbol}] Order failed — check logs.")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="FAILED")


# ── Full scan cycle ────────────────────────────────────────────────────────────

def _detect_and_notify_closed_positions(
    current_tickets: set,
    fetcher:         MT5DataFetcher,
    pos_mgr:         MT5PositionManager,
    logger_db:       TradeLogger,
    scan_epoch:      float,
) -> None:
    """
    Compare tracked _pos_state tickets against live MT5 positions.
    Tickets that vanished from MT5 have closed — retrieve their deal
    from MT5 history and notify the AI engine + TradeLogger.
    """
    closed_tickets = [t for t in list(_pos_state) if t not in current_tickets]
    if not closed_tickets:
        return

    # Query MT5 deal history for the last 10 minutes to catch recent closes
    deals = pos_mgr.get_recently_closed_deals(since_epoch=scan_epoch - 600)
    deal_map = {d["ticket"]: d for d in deals}

    for ticket in closed_tickets:
        state = _pos_state.get(ticket, {})
        deal  = deal_map.get(ticket)

        profit     = float(deal["profit"])      if deal else 0.0
        exit_price = float(deal["exit_price"])  if deal else state.get("entry_price", 0.0)
        close_ts   = float(deal["close_time_epoch"]) if deal else scan_epoch

        logger.info(
            "[AI] Position closed: ticket=%d %s %s profit=%.2f",
            ticket, state.get("symbol"), state.get("direction"), profit,
        )

        # Update TradeLogger close record
        logger_db.log_trade_close(ticket, exit_price, profit, reason="detected")

        # Update learning outcome (WIN/LOSS + realised RR)
        logger_db.update_learning_outcome(
            ticket       = ticket,
            profit       = profit,
            entry_price  = float(state.get("entry_price", 0)),
            exit_price   = exit_price,
        )

        # Notify AI engine for RL online update
        if _ai_engine is not None:
            trade_result = {
                "ticket":           ticket,
                "profit":           profit,
                "rr_achieved":      0.0,    # approximated inside update_learning_outcome
                "direction":        state.get("direction", ""),
                "h1_trend":         (state.get("market_snapshot") or {}).get("h1_trend", ""),
                "close_time_epoch": close_ts,
            }
            current_market = {
                "h1_trend": "NEUTRAL",   # best available without a live fetch here
                "rsi":      None,
                "atr":      state.get("atr"),
                "session":  current_session(),
            }
            _ai_engine.on_trade_close(
                trade_result   = trade_result,
                entry_market   = state.get("market_snapshot"),
                current_market = current_market,
            )


def run_scan(
    fetcher:    MT5DataFetcher,
    executor:   MT5Executor,
    pos_mgr:    MT5PositionManager,
    logger_db:  TradeLogger,
    scan:       int,
) -> None:
    import time as _time
    scan_epoch = _time.time()

    # Re-evaluate trading phase every scan — auto-escalates when trade count crosses threshold
    trade_count   = logger_db.get_closed_trade_count()
    current_phase = config.apply_trading_phase(trade_count)

    session = current_session()
    display_header(scan, session)

    acct = fetcher.get_account_info()
    display_account(acct)

    positions = pos_mgr.get_open_positions()
    display_positions(positions)

    # Position management runs every cycle regardless of session (Upgrade 4)
    if positions:
        manage_open_positions(positions, fetcher, executor)

    # Detect positions that closed since last scan → notify AI + update DB
    current_tickets = {p["ticket"] for p in positions}
    _detect_and_notify_closed_positions(
        current_tickets, fetcher, pos_mgr, logger_db, scan_epoch
    )

    # Session gate (Upgrade 3) — no new entries outside active sessions
    if not session:
        _line()
        print("  Outside trading sessions — skipping new entries.")
        display_stats(logger_db.get_statistics())
        return

    for symbol in config.SYMBOLS:
        try:
            scan_symbol(symbol, fetcher, executor, pos_mgr, logger_db, session=session)
        except Exception as exc:
            logger.error(f"[{symbol}] Error during scan: {exc}")
            traceback.print_exc()

    display_stats(logger_db.get_statistics())


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print()
    _line("═")
    print("  GOLD TRADING BOT  —  MT5 MULTI-SYMBOL  v2.0")
    print(f"  Symbols    : {', '.join(config.SYMBOLS)}")
    print(
        f"  Timeframes : {config.HTF_TIMEFRAME} bias → "
        f"{config.TREND_TIMEFRAME} trend → "
        f"{config.CONFIRM_TIMEFRAME} confirm → "
        f"{config.ENTRY_TIMEFRAME} entry → {config.TIMING_TIMEFRAME} timing"
    )
    sess_str = "  |  ".join(
        f"{k} {v[0]:02d}:00–{v[1]:02d}:00 UTC"
        for k, v in config.SESSIONS.items()
    )
    print(f"  Sessions   : {sess_str}")
    print(f"  Account    : {config.MT5_LOGIN}  |  {config.MT5_SERVER}")
    print(f"  Mode       : {config.ACCOUNT_TYPE}  |  DATA COLLECTION")
    print(
        f"  Risk       : {config.RISK_PER_TRADE:.1%}/trade  |  "
        f"Max DD: {config.MAX_DAILY_LOSS:.1%}  |  "
        f"Max positions: {config.MAX_POSITIONS}"
    )
    print(
        f"  Partial TP : {config.PARTIAL_TP_RATIO:.0%} at {config.BREAKEVEN_AT_R}R  |  "
        f"Trail start: {config.TRAIL_START_AT_R}R @ {config.TRAIL_ATR_MULT}×ATR"
    )
    print(
        f"  Volume gate: ≥{config.VOLUME_MIN_RATIO:.0%} of {config.VOLUME_LOOKBACK}-bar avg  |  "
        f"RSI bull zone: [{config.RSI_BULL_MIN}–{config.RSI_BULL_MAX}]  "
        f"bear zone: [{config.RSI_BEAR_MIN}–{config.RSI_BEAR_MAX}]"
    )
    _line("═")
    print()

    fetcher = MT5DataFetcher()
    if not fetcher.connect():
        logger.critical("MT5 connection failed.")
        sys.exit(1)

    executor  = MT5Executor(fetcher)
    pos_mgr   = MT5PositionManager(fetcher)
    logger_db = TradeLogger("data/trading_mt5.db")

    # ── AI Learning Engine ─────────────────────────────────────────────────────
    global _ai_engine
    _ai_engine = LearningEngine(db_path="data/trading_mt5.db")
    _ai_engine.load_models()

    # Apply trading phase based on how many closed trades we already have
    trade_count   = logger_db.get_closed_trade_count()
    current_phase = config.apply_trading_phase(trade_count)
    logger.info(
        "Trading phase %d  (closed trades=%d)  "
        "MIN_SCORE=%d  volume_ratio=%.0f%%  H4_hard_gate=%s",
        current_phase, trade_count,
        config.MIN_SCORE, config.VOLUME_MIN_RATIO * 100, config.H4_HARD_GATE,
    )

    # Apply any previously learned parameter improvements (overrides phase RSI only)
    live_params = _ai_engine.get_live_params()
    if live_params.get("rsi_bull_min"):
        config.RSI_BULL_MIN = int(live_params["rsi_bull_min"])
        config.RSI_BULL_MAX = int(live_params["rsi_bull_max"])
        config.RSI_BEAR_MIN = int(live_params["rsi_bear_min"])
        config.RSI_BEAR_MAX = int(live_params["rsi_bear_max"])
        logger.info(
            "AI params loaded: bull RSI[%d–%d]  bear RSI[%d–%d]",
            config.RSI_BULL_MIN, config.RSI_BULL_MAX,
            config.RSI_BEAR_MIN, config.RSI_BEAR_MAX,
        )

    acct = fetcher.get_account_info()
    if not acct:
        logger.critical("Cannot read account info.")
        fetcher.disconnect()
        sys.exit(1)

    pos_mgr.set_session_start_balance(acct["balance"])
    session_id = logger_db.start_session(acct["balance"])
    logger.info(
        f"Session {session_id} | "
        f"{len(config.SYMBOLS)} symbols | "
        f"balance={acct['balance']:.2f} {acct['currency']}"
    )

    scan       = 0
    start_time = time.time()

    try:
        while True:
            scan += 1
            cycle_start = time.time()

            try:
                run_scan(fetcher, executor, pos_mgr, logger_db, scan)
            except Exception as exc:
                logger.error(f"Scan #{scan} error: {exc}")
                traceback.print_exc()

            if config.RUN_ONCE:
                print("\n  RUN_ONCE=True — exiting.")
                break

            elapsed   = time.time() - cycle_start
            sleep_for = max(0, config.SCAN_INTERVAL - elapsed)
            _line()
            print(f"  Next scan in {sleep_for:.0f}s  (Ctrl+C to stop)")
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\n\n  Stopping bot...")

    finally:
        runtime = timedelta(seconds=int(time.time() - start_time))
        final   = fetcher.get_account_info() or {}
        stats   = logger_db.get_statistics()

        if _ai_engine is not None:
            _ai_engine.on_session_end()
            _ai_engine.shutdown()

        logger_db.end_session(final.get("balance", 0))
        logger_db.close()
        fetcher.disconnect()

        _line("═")
        print("  SESSION SUMMARY")
        _line("═")
        print(f"  Runtime      : {runtime}")
        print(f"  Scans        : {scan}")
        print(f"  Symbols      : {', '.join(config.SYMBOLS)}")
        print(f"  Start balance: {acct['balance']:.2f} {acct.get('currency', '')}")
        print(f"  End balance  : {final.get('balance', 0):.2f}")
        print(f"  Net P&L      : {final.get('balance', 0) - acct['balance']:.2f}")
        print(f"  Total trades : {stats.get('total_trades', 0)}")
        print(f"  Win rate     : {stats.get('win_rate', 0):.1f}%")
        print(f"  Profit factor: {stats.get('profit_factor', 0):.2f}")
        _line("═")
        print()


if __name__ == "__main__":
    main()
