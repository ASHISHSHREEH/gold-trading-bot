"""
GOLD TRADING BOT — MT5 MULTI-SYMBOL LIVE EDITION
=================================================
Trades GOLD, S&P 500, NASDAQ 100, Japan 225 simultaneously.

Every scan cycle:
  For each symbol in MT5_SYMBOLS:
    1. Fetch M15 candles  → MA trend (20/50)
    2. Fetch M1  candles  → RSI + MACD + Bollinger entry signals + ATR
    3. Score confluence   → need trend + 2-of-3 indicators
    4. Account-wide risk gates (max positions / drawdown / margin)
    5. Symbol-level gate  → skip if already in this symbol
    6. Execute via mt5.order_send()
    7. Log to SQLite

Prerequisites:
    pip install -r requirements.txt
    MT5_SYMBOLS=GOLD,#USSPX500,#US100_M26,#Japan225  in .env
"""

import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
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
_MA_PERIODS = [20, 50]

# Human-readable labels for display
_SYMBOL_LABELS = {
    "GOLD":       "Gold   (XAU)",
    "#USSPX500":  "S&P500 (US)",
    "#US100_M26": "NASDAQ (US)",
    "#Japan225":  "Nikkei (JP)",
}


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyse_trend(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    df = fetcher.get_historical_data(config.TREND_TIMEFRAME, config.TREND_CANDLES, symbol)
    if df.empty or len(df) < _MA_PERIODS[-1] + 5:
        logger.warning(f"[{symbol}] Insufficient M15 data.")
        return None

    ma_df = _IND["ma"].calculate_multiple_mas(df["close"], periods=_MA_PERIODS)
    df    = df.join(ma_df)
    ana   = _IND["ma"].analyze_latest(df["close"].iloc[:-1], ma_df.iloc[:-1])

    return {
        "price":     float(df["close"].iloc[-2]),
        "timestamp": df.index[-2],
        "ma_fast":   ana["ma_fast"],
        "ma_slow":   ana["ma_slow"],
        "trend":     ana["trend"],
    }


def analyse_entry(fetcher: MT5DataFetcher, symbol: str) -> Optional[Dict[str, Any]]:
    df = fetcher.get_historical_data(config.ENTRY_TIMEFRAME, config.ENTRY_CANDLES, symbol)
    if df.empty or len(df) < 30:
        logger.warning(f"[{symbol}] Insufficient M1 data.")
        return None

    df["rsi"] = _IND["rsi"].calculate_rsi(df)
    macd_df   = _IND["macd"].calculate_macd(df)
    df        = df.join(macd_df)
    bb_df     = _IND["bb"].calculate_bands(df["close"])
    df        = df.join(bb_df)
    atr_val   = _IND["atr"].get_latest(df)

    return {
        "price":     float(df["close"].iloc[-1]),
        "timestamp": df.index[-1],
        "atr":       atr_val,
        "rsi":       _IND["rsi"].analyze_latest(df),
        "macd":      _IND["macd"].analyze_latest(macd_df),
        "bb":        _IND["bb"].analyze_latest(df["close"], bb_df),
    }


def generate_signal(trend: Dict, entry: Dict) -> Dict[str, Any]:
    trend_dir = trend["trend"]
    is_bull   = trend_dir in ("STRONG_BULL", "BULL")
    is_bear   = trend_dir in ("STRONG_BEAR", "BEAR")

    rsi  = entry["rsi"]
    macd = entry["macd"]
    bb   = entry["bb"]

    score   = 0
    reasons = [f"M15: {trend_dir}"]

    if is_bull:
        if rsi["signal"]  == "BUY": score += 1; reasons.append(f"RSI oversold ({rsi['rsi']:.1f})")
        if macd["signal"] == "BUY": score += 1; reasons.append("MACD bullish")
        if bb["position"] in ("NEAR_LOWER", "BELOW_LOWER", "WALKING_UP"):
            score += 1; reasons.append(f"BB {bb['position']}")
        signal = "BUY" if score >= 2 else "NEUTRAL"

    elif is_bear:
        if rsi["signal"]  == "SELL": score += 1; reasons.append(f"RSI overbought ({rsi['rsi']:.1f})")
        if macd["signal"] == "SELL": score += 1; reasons.append("MACD bearish")
        if bb["position"] in ("NEAR_UPPER", "ABOVE_UPPER", "WALKING_DOWN"):
            score += 1; reasons.append(f"BB {bb['position']}")
        signal = "SELL" if score >= 2 else "NEUTRAL"

    else:
        signal = "NEUTRAL"
        reasons.append("No clear trend — standing aside")

    confidence = "HIGH" if score >= 3 else ("MODERATE" if score == 2 else "LOW")

    return {
        "signal":     signal,
        "confidence": confidence,
        "score":      score,
        "reasons":    reasons,
        "trend":      trend_dir,
        "rsi":        rsi.get("rsi"),
        "macd":       macd["signal"],
        "bb":         bb["position"],
    }


# ── Display ────────────────────────────────────────────────────────────────────

def _line(char="─", w=70): print(char * w)

def display_header(scan: int):
    _line("═")
    print(
        f"  SCAN #{scan}  |  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  |  "
        f"Symbols: {', '.join(config.SYMBOLS)}"
    )
    _line("═")

def display_account(acct: Dict):
    if not acct: return
    print(
        f"  ACCOUNT  Balance: {acct['balance']:,.2f} {acct['currency']}  |  "
        f"Equity: {acct['equity']:,.2f}  |  "
        f"Free Margin: {acct['free_margin']:,.2f}  |  "
        f"Leverage: 1:{acct['leverage']}"
    )

def display_positions(positions: List[Dict]):
    _line()
    total = len(positions)
    print(f"  OPEN POSITIONS  ({total}/{config.MAX_POSITIONS})")
    if not positions:
        print("  No open positions.")
        return
    for p in positions:
        sign  = "+" if p["profit"] >= 0 else ""
        label = _SYMBOL_LABELS.get(p["symbol"], p["symbol"])
        print(
            f"    #{p['ticket']}  {label}  {p['direction']:<4}  "
            f"entry={p['entry_price']:.2f}  now={p['current_price']:.2f}  "
            f"SL={p['sl']:.2f}  TP={p['tp']:.2f}  "
            f"P&L={sign}{p['profit']:.2f}"
        )

def display_symbol_analysis(symbol: str, signal_data: Dict, trend: Dict, entry: Dict):
    label = _SYMBOL_LABELS.get(symbol, symbol)
    sig   = signal_data["signal"]
    icon  = {"BUY": "▲ BUY", "SELL": "▼ SELL", "NEUTRAL": "● NEUTRAL"}[sig]

    _line()
    print(f"  [{label}]")
    print(
        f"  M15 Trend: {trend['trend']:<12}  "
        f"MA20={trend['ma_fast']:.2f}  MA50={trend['ma_slow']:.2f}"
    )
    print(
        f"  M1  Entry: price={entry['price']:.2f}  "
        f"ATR={entry['atr']:.4f}  "
        f"RSI={entry['rsi']['rsi']:.1f}  "
        f"MACD={entry['macd']['signal']}  "
        f"BB={entry['bb']['position']}"
    )
    print(
        f"  {icon}  |  Score: {signal_data['score']}/3  |  "
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
):
    trend = analyse_trend(fetcher, symbol)
    entry = analyse_entry(fetcher, symbol)

    if trend is None or entry is None:
        print(f"  [{symbol}] Data unavailable — skipping.")
        return

    signal_data = generate_signal(trend, entry)
    display_symbol_analysis(symbol, signal_data, trend, entry)

    # Log every signal for strategy audit
    logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="PENDING")

    risk = pos_mgr.check_risk_limits(symbol=symbol)

    if not risk["can_open_new"]:
        print(f"  GATE: {'; '.join(risk['reasons'])}")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="BLOCKED")
        return

    if signal_data["signal"] == "NEUTRAL":
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="NEUTRAL")
        return

    # Execute
    execution = executor.execute_signal(
        signal    = signal_data["signal"],
        atr_value = entry["atr"],
        symbol    = symbol,
    )

    if execution:
        display_execution(symbol, execution)
        logger_db.log_trade_open(execution)
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="EXECUTED")
    else:
        print(f"  [{symbol}] Order failed — check logs.")
        logger_db.log_signal(signal_data, entry["price"], entry["atr"], action="FAILED")


# ── Full scan cycle ────────────────────────────────────────────────────────────

def run_scan(
    fetcher:   MT5DataFetcher,
    executor:  MT5Executor,
    pos_mgr:   MT5PositionManager,
    logger_db: TradeLogger,
    scan:      int,
):
    display_header(scan)

    acct = fetcher.get_account_info()
    display_account(acct)

    positions = pos_mgr.get_open_positions()
    display_positions(positions)

    for symbol in config.SYMBOLS:
        try:
            scan_symbol(symbol, fetcher, executor, pos_mgr, logger_db)
        except Exception as exc:
            logger.error(f"[{symbol}] Error during scan: {exc}")
            traceback.print_exc()

    display_stats(logger_db.get_statistics())


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print()
    _line("═")
    print("  GOLD TRADING BOT  —  MT5 MULTI-SYMBOL LIVE EDITION")
    print(f"  Symbols : {', '.join(config.SYMBOLS)}")
    print(f"  Account : {config.MT5_LOGIN}  |  {config.MT5_SERVER}")
    print(f"  Mode    : {config.ACCOUNT_TYPE}")
    print(
        f"  Risk    : {config.RISK_PER_TRADE:.1%}/trade  |  "
        f"Max DD: {config.MAX_DAILY_LOSS:.1%}  |  "
        f"Max positions: {config.MAX_POSITIONS}"
    )
    _line("═")
    print()

    fetcher   = MT5DataFetcher()
    if not fetcher.connect():
        logger.critical("MT5 connection failed.")
        sys.exit(1)

    executor  = MT5Executor(fetcher)
    pos_mgr   = MT5PositionManager(fetcher)
    logger_db = TradeLogger("data/trading_mt5.db")

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
        final   = fetcher.get_account_info()
        stats   = logger_db.get_statistics()

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
