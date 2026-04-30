"""
GOLD TRADING BOT — MT5 LIVE EXECUTION ENGINE
=============================================
Architecture:
    MT5 Terminal  →  MT5DataFetcher  (market data, account info)
                  →  ATRCalculator   (volatility stops)
                  →  Indicator stack (MA trend, RSI, MACD, BB entry signals)
                  →  Signal scoring  (trend + 2-of-3 confluence)
                  →  Risk gates      (positions / drawdown / margin)
                  →  MT5Executor     (live mt5.order_send())
                  →  TradeLogger     (SQLite analytics — offline only)

Scan cycle: every 60 seconds (configurable via config.SCAN_INTERVAL)
Prerequisites:
    1. MT5 terminal open and logged in on the same machine
    2. .env populated with credentials (see .env.example)
    3. pip install -r requirements.txt
"""

import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import config

# Fail fast if someone accidentally sets ACCOUNT_TYPE=LIVE
config.assert_demo_mode()

from data.mt5_fetcher       import MT5DataFetcher
from indicators.atr          import ATRCalculator
from indicators.rsi          import RSICalculator
from indicators.macd         import MACDCalculator
from indicators.bollinger    import BollingerBandsCalculator
from indicators.moving_average import MovingAverageCalculator
from trading.mt5_executor    import MT5Executor
from trading.mt5_position_manager import MT5PositionManager
from database.trade_logger   import TradeLogger

# ── Logging Setup ──────────────────────────────────────────────────────────────
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

# Suppress noisy sub-loggers during normal operation
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("MetaTrader5").setLevel(logging.WARNING)


# ── Indicator Instances (stateless; reused each scan) ─────────────────────────
_INDICATORS = {
    "atr":  ATRCalculator(period=config.ATR_PERIOD),
    "rsi":  RSICalculator(period=14),
    "macd": MACDCalculator(),
    "bb":   BollingerBandsCalculator(period=20, std_dev=2),
    "ma":   MovingAverageCalculator(),
}

_MA_PERIODS = [20, 50]


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyse_trend(fetcher: MT5DataFetcher) -> Optional[Dict[str, Any]]:
    """
    Fetch M15 candles and determine broad trend direction via 20/50 MA.
    Uses the second-to-last (confirmed, closed) candle to avoid repainting.
    """
    df = fetcher.get_historical_data(config.TREND_TIMEFRAME, config.TREND_CANDLES)
    if df.empty or len(df) < _MA_PERIODS[-1] + 5:
        logger.warning("Insufficient M15 data for trend analysis.")
        return None

    ma_df  = _INDICATORS["ma"].calculate_multiple_mas(df["close"], periods=_MA_PERIODS)
    df     = df.join(ma_df)

    # -2 = last confirmed closed candle (anti-repainting)
    ana   = _INDICATORS["ma"].analyze_latest(df["close"].iloc[:-1], ma_df.iloc[:-1])
    return {
        "price":      float(df["close"].iloc[-2]),
        "timestamp":  df.index[-2],
        "ma_fast":    ana["ma_fast"],
        "ma_slow":    ana["ma_slow"],
        "trend":      ana["trend"],   # STRONG_BULL | BULL | NEUTRAL | BEAR | STRONG_BEAR
    }


def analyse_entry(fetcher: MT5DataFetcher) -> Optional[Dict[str, Any]]:
    """
    Fetch M1 candles and score RSI, MACD, Bollinger entry signals.
    Uses the live (current) candle for tactical timing.
    """
    df = fetcher.get_historical_data(config.ENTRY_TIMEFRAME, config.ENTRY_CANDLES)
    if df.empty or len(df) < 30:
        logger.warning("Insufficient M1 data for entry analysis.")
        return None

    df["rsi"]  = _INDICATORS["rsi"].calculate_rsi(df)
    macd_df    = _INDICATORS["macd"].calculate_macd(df)
    df         = df.join(macd_df)
    bb_df      = _INDICATORS["bb"].calculate_bands(df["close"])
    df         = df.join(bb_df)

    atr_val    = _INDICATORS["atr"].get_latest(df)

    rsi_ana  = _INDICATORS["rsi"].analyze_latest(df)
    macd_ana = _INDICATORS["macd"].analyze_latest(macd_df)
    bb_ana   = _INDICATORS["bb"].analyze_latest(df["close"], bb_df)

    return {
        "price":        float(df["close"].iloc[-1]),
        "timestamp":    df.index[-1],
        "atr":          atr_val,
        "df":           df,           # full frame — needed for ATR bands later
        "rsi":          rsi_ana,
        "macd":         macd_ana,
        "bb":           bb_ana,
    }


def generate_signal(
    trend: Dict[str, Any],
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Confluence scoring:
        • Trend direction from M15 MA (BULL / BEAR required — NEUTRAL blocked)
        • Need 2 of 3 entry indicators aligned with trend on M1
        • Score 3/3 → HIGH confidence; 2/3 → MODERATE; <2 → NEUTRAL
    """
    trend_dir    = trend["trend"]
    is_bull      = trend_dir in ("STRONG_BULL", "BULL")
    is_bear      = trend_dir in ("STRONG_BEAR", "BEAR")

    rsi  = entry["rsi"]
    macd = entry["macd"]
    bb   = entry["bb"]

    score   = 0
    reasons = [f"M15 trend: {trend_dir}"]

    if is_bull:
        if rsi["signal"] == "BUY":
            score += 1
            reasons.append(f"RSI oversold ({rsi['rsi']:.1f})")
        if macd["signal"] == "BUY":
            score += 1
            reasons.append("MACD bullish crossover")
        if bb["position"] in ("NEAR_LOWER", "BELOW_LOWER", "WALKING_UP"):
            score += 1
            reasons.append(f"BB {bb['position']}")

        signal = "BUY" if score >= 2 else "NEUTRAL"

    elif is_bear:
        if rsi["signal"] == "SELL":
            score += 1
            reasons.append(f"RSI overbought ({rsi['rsi']:.1f})")
        if macd["signal"] == "SELL":
            score += 1
            reasons.append("MACD bearish crossover")
        if bb["position"] in ("NEAR_UPPER", "ABOVE_UPPER", "WALKING_DOWN"):
            score += 1
            reasons.append(f"BB {bb['position']}")

        signal = "SELL" if score >= 2 else "NEUTRAL"

    else:
        signal  = "NEUTRAL"
        reasons.append("No clear trend — standing aside")

    confidence = "HIGH" if score >= 3 else ("MODERATE" if score == 2 else "LOW")

    return {
        "signal":     signal,
        "confidence": confidence,
        "score":      score,
        "reasons":    reasons,
        "trend":      trend_dir,
        "rsi":        rsi["rsi"] if "rsi" in rsi else None,
        "macd":       macd["signal"],
        "bb":         bb["position"],
    }


# ── Terminal Display ───────────────────────────────────────────────────────────

def _line(char="─", width=70):
    print(char * width)


def display_header(scan: int):
    _line("═")
    print(
        f"  GOLD TRADING BOT  |  Scan #{scan}  |  "
        f"{datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}"
    )
    _line("═")


def display_account(acct: Dict[str, Any]):
    if not acct:
        return
    print(f"  ACCOUNT  |  Balance: {acct['balance']:,.2f} {acct['currency']}"
          f"  |  Equity: {acct['equity']:,.2f}"
          f"  |  Free Margin: {acct['free_margin']:,.2f}"
          f"  |  Leverage: 1:{acct['leverage']}")


def display_positions(positions):
    _line()
    count = len(positions)
    label = "FULL" if count >= config.MAX_POSITIONS else "OK"
    print(f"  OPEN POSITIONS  ({count}/{config.MAX_POSITIONS})  [{label}]")
    if not positions:
        print("  No open positions.")
    for p in positions:
        sign = "+" if p["profit"] >= 0 else ""
        print(
            f"    #{p['ticket']}  {p['direction']:<4}  "
            f"entry={p['entry_price']:.2f}  "
            f"now={p['current_price']:.2f}  "
            f"SL={p['sl']:.2f}  TP={p['tp']:.2f}  "
            f"P&L={sign}{p['profit']:.2f}"
        )


def display_signal(signal_data, trend, entry):
    _line()
    icon = {"BUY": "▲  BUY", "SELL": "▼  SELL", "NEUTRAL": "●  NEUTRAL"}
    sig  = signal_data["signal"]
    print(
        f"  M15 TREND: {trend['trend']:<12}  "
        f"MA20={trend['ma_fast']:.2f}  MA50={trend['ma_slow']:.2f}  "
        f"(confirmed {trend['timestamp'].strftime('%H:%M')})"
    )
    print(
        f"  M1  ENTRY: price={entry['price']:.2f}  "
        f"ATR={entry['atr']:.2f}  "
        f"RSI={entry['rsi']['rsi']:.1f}  "
        f"MACD={entry['macd']['signal']}  "
        f"BB={entry['bb']['position']}"
    )
    _line()
    print(f"  {icon.get(sig, sig)}  |  Confidence: {signal_data['confidence']}"
          f"  |  Score: {signal_data['score']}/3")
    print(f"  Reasons: {'; '.join(signal_data['reasons'])}")


def display_execution(execution: Dict[str, Any]):
    _line()
    print(
        f"  EXECUTED {execution['direction']}  "
        f"ticket={execution['ticket']}  "
        f"@ {execution['entry_price']:.2f}  "
        f"vol={execution['volume']} lots"
    )
    print(
        f"  SL={execution['stop_loss']:.2f}  "
        f"TP={execution['take_profit']:.2f}  "
        f"ATR={execution['atr']:.2f}  "
        f"R:R={execution['rr_ratio']:.2f}  "
        f"Risk={execution['risk_amount']:.2f}"
    )


def display_stats(stats: Dict[str, Any]):
    if not stats or not stats.get("total_trades"):
        return
    _line()
    print(
        f"  SESSION STATS  |  "
        f"Trades: {stats['total_trades']}  |  "
        f"Win rate: {stats['win_rate']:.1f}%  |  "
        f"P-factor: {stats['profit_factor']:.2f}  |  "
        f"Net P&L: {stats.get('total_profit', 0):.2f}"
    )


# ── Main Scan Cycle ────────────────────────────────────────────────────────────

def run_scan(
    fetcher:  MT5DataFetcher,
    executor: MT5Executor,
    pos_mgr:  MT5PositionManager,
    logger_db: TradeLogger,
    scan:     int,
):
    display_header(scan)

    # ── 1. Fetch account state ────────────────────────────────────────────────
    acct = fetcher.get_account_info()
    display_account(acct)

    # ── 2. Show open positions ────────────────────────────────────────────────
    positions = pos_mgr.get_open_positions()
    display_positions(positions)

    # ── 3. Market analysis ────────────────────────────────────────────────────
    print("\n  Analysing market...")
    trend  = analyse_trend(fetcher)
    entry  = analyse_entry(fetcher)

    if trend is None or entry is None:
        print("  Data fetch failed — skipping scan.")
        return

    # ── 4. Signal generation ─────────────────────────────────────────────────
    signal_data = generate_signal(trend, entry)
    display_signal(signal_data, trend, entry)

    # ── 5. Risk gates ─────────────────────────────────────────────────────────
    risk = pos_mgr.check_risk_limits()
    _line()

    # Log the signal regardless of whether we trade
    logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="PENDING")

    if not risk["can_open_new"]:
        print(f"  RISK GATE: {'; '.join(risk['reasons'])}")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="BLOCKED")
        return

    if signal_data["signal"] == "NEUTRAL":
        print("  No actionable signal — standing aside.")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="NEUTRAL")
        return

    # ── 6. Execute ────────────────────────────────────────────────────────────
    print(f"  All gates clear — sending {signal_data['signal']} order...")
    execution = executor.execute_signal(
        signal   = signal_data["signal"],
        atr_value= entry["atr"],
    )

    if execution:
        display_execution(execution)
        logger_db.log_trade_open(execution)
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="EXECUTED")
    else:
        print("  Order failed — check logs for details.")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="FAILED")

    # ── 7. Session analytics ──────────────────────────────────────────────────
    display_stats(logger_db.get_statistics())


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 70)
    print("  GOLD TRADING BOT  —  MT5 LIVE EDITION")
    print(f"  Symbol  : {config.SYMBOL}")
    print(f"  Account : {config.MT5_LOGIN}  |  {config.MT5_SERVER}")
    print(f"  Mode    : {config.ACCOUNT_TYPE}")
    print(f"  Risk    : {config.RISK_PER_TRADE:.1%}/trade  |  "
          f"Max DD: {config.MAX_DAILY_LOSS:.1%}  |  "
          f"Max positions: {config.MAX_POSITIONS}")
    print("=" * 70)
    print()

    # ── Initialise components ─────────────────────────────────────────────────
    fetcher   = MT5DataFetcher()
    if not fetcher.connect():
        logger.critical("MT5 connection failed. Is the terminal open and logged in?")
        sys.exit(1)

    executor  = MT5Executor(fetcher)
    pos_mgr   = MT5PositionManager(fetcher)
    logger_db = TradeLogger("data/trading_mt5.db")

    acct = fetcher.get_account_info()
    if not acct:
        logger.critical("Cannot read account info after connection.")
        fetcher.disconnect()
        sys.exit(1)

    pos_mgr.set_session_start_balance(acct["balance"])
    session_id = logger_db.start_session(acct["balance"])
    logger.info(f"Session {session_id} started | balance={acct['balance']:.2f} {acct['currency']}")

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
                print("\n  RUN_ONCE=True — exiting after first scan.")
                break

            elapsed    = time.time() - cycle_start
            sleep_for  = max(0, config.SCAN_INTERVAL - elapsed)
            _line()
            print(f"  Next scan in {sleep_for:.0f}s  (Ctrl+C to stop)")
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\n\n  Stopping bot...")

    finally:
        # ── Graceful shutdown ─────────────────────────────────────────────────
        runtime = timedelta(seconds=int(time.time() - start_time))
        final   = fetcher.get_account_info()
        stats   = logger_db.get_statistics()

        logger_db.end_session(final.get("balance", 0))
        logger_db.close()
        fetcher.disconnect()

        print()
        _line("═")
        print("  SESSION SUMMARY")
        _line("═")
        print(f"  Runtime      : {runtime}")
        print(f"  Total scans  : {scan}")
        print(f"  Start balance: {acct['balance']:.2f} {acct.get('currency', '')}")
        print(f"  End balance  : {final.get('balance', 0):.2f}")
        print(f"  Net P&L      : {final.get('balance', 0) - acct['balance']:.2f}")
        print(f"  Total trades : {stats.get('total_trades', 0)}")
        print(f"  Win rate     : {stats.get('win_rate', 0):.1f}%")
        print(f"  Profit factor: {stats.get('profit_factor', 0):.2f}")
        _line("═")
        print("  Goodbye.")
        print()


if __name__ == "__main__":
    main()
