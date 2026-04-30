"""
GOLD TRADING BOT — MT5 EDITION  v2.0
=====================================
Full MetaTrader 5 integration:
  • Live data  → MT5 terminal
  • Execution  → MT5 market orders (SL/TP managed by broker server)
  • Analytics  → SQLite trade log (performance tracking only)

Execution cycle (every SCAN_INTERVAL seconds):
  1. Fetch 15m bars  → trend direction (MA cross)
  2. Fetch 1m bars   → entry signals (RSI + MACD + BB)
  3. Calculate ATR   → stop/target placement
  4. Generate signal → Multi-TF confluence scoring
  5. Risk gate       → max positions / daily drawdown / margin
  6. Execute         → mt5.order_send() with SL/TP
  7. Log             → SQLite for analytics
"""

import sys
import time
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import config

# ── Safety guard — will raise if ACCOUNT_TYPE=LIVE ─────────────────────────
config.assert_demo_mode()

# ── MT5 Components ──────────────────────────────────────────────────────────
from data.mt5_fetcher          import MT5DataFetcher
from trading.mt5_executor      import MT5Executor
from trading.mt5_position_manager import MT5PositionManager
from database.trade_logger     import TradeLogger

# ── Indicators (unchanged — pure pandas, no MT5 dependency) ─────────────────
from indicators.rsi            import RSICalculator
from indicators.macd           import MACDCalculator
from indicators.bollinger      import BollingerBandsCalculator
from indicators.moving_average import MovingAverageCalculator
from indicators.atr            import ATRCalculator

# ── Logging ─────────────────────────────────────────────────────────────────
import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot_mt5.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("GoldBot_MT5")


# ═══════════════════════════════════════════════════════════════════════════
# INITIALISATION
# ═══════════════════════════════════════════════════════════════════════════

def initialize() -> Dict[str, Any]:
    print("=" * 68)
    print("  GOLD TRADING BOT  v2.0  |  MT5 Edition")
    print(f"  Account: {config.MT5_LOGIN}  |  Server: {config.MT5_SERVER}")
    print(f"  Symbol:  {config.SYMBOL}     |  Mode: {config.ACCOUNT_TYPE}")
    print("=" * 68)

    # 1. Data fetcher + MT5 connection
    fetcher = MT5DataFetcher(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
        symbol=config.SYMBOL,
    )
    fetcher.connect()

    if not fetcher.validate_connection():
        raise RuntimeError(f"Validation failed — cannot fetch data for {config.SYMBOL}")

    sym_info = fetcher.get_symbol_info()
    logger.info(
        f"Symbol info | contract={sym_info['contract_size']} oz/lot | "
        f"min_lot={sym_info['volume_min']} | digits={sym_info['digits']}"
    )

    # 2. Execution + position management
    executor    = MT5Executor(fetcher)
    pos_manager = MT5PositionManager(fetcher)
    pos_manager.initialize_session()

    # 3. Analytics logger
    account    = fetcher.get_account_info()
    trade_log  = TradeLogger()
    session_id = trade_log.start_session(account["balance"])

    # 4. Indicators
    indicators = {
        "rsi":  RSICalculator(period=config.RSI_PERIOD,
                              overbought=config.RSI_OVERBOUGHT,
                              oversold=config.RSI_OVERSOLD),
        "macd": MACDCalculator(),
        "bb":   BollingerBandsCalculator(period=config.BB_PERIOD,
                                         std_dev=config.BB_STD),
        "ma":   MovingAverageCalculator(),
        "atr":  ATRCalculator(period=config.ATR_PERIOD),
    }

    print(f"\n  ALL SYSTEMS READY  |  Scanning every {config.SCAN_INTERVAL}s\n")

    return {
        "fetcher":    fetcher,
        "executor":   executor,
        "pos_mgr":    pos_manager,
        "trade_log":  trade_log,
        "session_id": session_id,
        "indicators": indicators,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def analyze_timeframe(
    fetcher: MT5DataFetcher,
    timeframe: str,
    candle_count: int,
    indicators: Dict,
    ma_periods,
    use_completed_candle: bool,
) -> Optional[Dict[str, Any]]:
    """
    Fetch bars, run all indicators, return analysis dict.
    use_completed_candle=True  → use iloc[-2] (confirmed, no repaint)
    use_completed_candle=False → use iloc[-1] (live, for entry timing)
    """
    df = fetcher.get_historical_data(timeframe, count=candle_count)

    if df.empty:
        logger.warning(f"No data for {timeframe}")
        return None

    min_required = max(ma_periods) + config.ATR_PERIOD + 5
    if len(df) < min_required:
        logger.warning(f"{timeframe}: need {min_required} bars, got {len(df)}")
        return None

    idx = -2 if use_completed_candle else -1

    # ── Moving Averages ──────────────────────────────────────────────────
    ma_df  = indicators["ma"].calculate_multiple_mas(df["close"], periods=ma_periods)
    df_ma  = df.join(ma_df)

    # ── Other Indicators ─────────────────────────────────────────────────
    df_ma["rsi"] = indicators["rsi"].calculate_rsi(df_ma)
    macd_df      = indicators["macd"].calculate_macd(df_ma)
    df_ma        = df_ma.join(macd_df)
    bb_df        = indicators["bb"].calculate_bands(df_ma["close"])
    df_ma        = df_ma.join(bb_df)

    # ── Slice to target candle (anti-repaint) ─────────────────────────────
    if idx == -1:
        sl = df_ma;   ma_sl = ma_df;   macd_sl = macd_df;   bb_sl = bb_df
    else:
        sl      = df_ma.iloc[:idx + 1]
        ma_sl   = ma_df.iloc[:idx + 1]
        macd_sl = macd_df.iloc[:idx + 1]
        bb_sl   = bb_df.iloc[:idx + 1]

    # ── Analyse latest ────────────────────────────────────────────────────
    ma_ana   = indicators["ma"].analyze_latest(sl["close"], ma_sl)
    rsi_ana  = indicators["rsi"].analyze_latest(sl)
    macd_ana = indicators["macd"].analyze_latest(macd_sl)
    bb_ana   = indicators["bb"].analyze_latest(sl["close"], bb_sl)

    # ── ATR on full df for accurate volatility ────────────────────────────
    atr_val  = indicators["atr"].get_latest(df)

    return {
        "price":        float(df["close"].iloc[idx]),
        "timestamp":    df.index[idx],
        "ma_analysis":  ma_ana,
        "rsi_analysis": rsi_ana,
        "macd_analysis":macd_ana,
        "bb_analysis":  bb_ana,
        "atr":          atr_val,
    }


def generate_signal(
    trend: Dict[str, Any],
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Multi-timeframe confluence:
      - Trade in the direction of the 15m MA trend
      - Require ≥ 2 entry confirmations (RSI + MACD + BB)
      - LOW confidence → no trade
    """
    signal     = "NEUTRAL"
    confidence = "LOW"
    reasons    = []
    score      = 0

    trend_dir      = trend["ma_analysis"]["trend"]
    is_bull_trend  = trend_dir in ("STRONG_BULL", "BULL")
    is_bear_trend  = trend_dir in ("STRONG_BEAR", "BEAR")

    reasons.append(f"15m trend: {trend_dir}")

    rsi  = entry["rsi_analysis"]
    macd = entry["macd_analysis"]
    bb   = entry["bb_analysis"]

    if is_bull_trend:
        if rsi["signal"] == "BUY":
            score += 1
            reasons.append(f"RSI oversold ({rsi['rsi']:.1f})")
        if macd["signal"] == "BUY":
            score += 1
            reasons.append("MACD bullish crossover")
        if bb["position"] in ("NEAR_LOWER", "BELOW_LOWER") or bb.get("signal") in ("BUY", "BUY_TREND"):
            score += 1
            reasons.append(f"BB: {bb['position']}")
        if score >= 2:
            signal = "BUY"

    elif is_bear_trend:
        if rsi["signal"] == "SELL":
            score += 1
            reasons.append(f"RSI overbought ({rsi['rsi']:.1f})")
        if macd["signal"] == "SELL":
            score += 1
            reasons.append("MACD bearish crossover")
        if bb["position"] in ("NEAR_UPPER", "ABOVE_UPPER") or bb.get("signal") in ("SELL", "SELL_TREND"):
            score += 1
            reasons.append(f"BB: {bb['position']}")
        if score >= 2:
            signal = "SELL"

    if score >= 3:
        confidence = "HIGH"
    elif score == 2:
        confidence = "MODERATE"
    else:
        signal     = "NEUTRAL"
        confidence = "LOW"

    return {
        "signal":       signal,
        "confidence":   confidence,
        "score":        score,
        "reasons":      reasons,
        "trend":        trend["ma_analysis"],
        "entry_analysis": entry,
        "symbol":       config.SYMBOL,
    }


# ═══════════════════════════════════════════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════════════════════════════════════════

def display_header(scan: int) -> None:
    print("=" * 68)
    print(f"  SCAN #{scan:04d}  |  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")

def display_account(account: Dict) -> None:
    dd_amount = account["balance"] - account["equity"]
    dd_sign   = "+" if dd_amount <= 0 else "-"
    print(f"  ACCOUNT  |  Balance: {account['balance']:,.2f} {account['currency']}"
          f"  |  Equity: {account['equity']:,.2f}"
          f"  |  Float P&L: {account['profit']:+.2f}"
          f"  |  Free Margin: {account['margin_free']:,.2f}")

def display_positions(summary: Dict) -> None:
    count = summary["count"]
    icon  = "FULL" if count >= config.MAX_POSITIONS else "OK"
    print(f"  POSITIONS ({count}/{config.MAX_POSITIONS}) [{icon}]")
    if count == 0:
        print("    No open positions")
    else:
        for p in summary["positions"]:
            print(
                f"    #{p['ticket']}  {p['direction']:<5}  "
                f"@ {p['entry_price']:.2f}  →  {p['current_price']:.2f}  "
                f"|  P&L: {p['profit']:+.2f}  "
                f"|  SL: {p['stop_loss']:.2f}  TP: {p['take_profit']:.2f}"
            )

def display_signal(signal_data: Dict, trend: Dict, entry: Dict) -> None:
    t = trend["ma_analysis"]
    print("─" * 68)
    print(f"  15m TREND  |  {t['trend']}  "
          f"|  MA{config.MA_FAST}: {t['ma_fast']:,.2f}  "
          f"|  MA{config.MA_SLOW}: {t['ma_slow']:,.2f}")

    rsi  = entry["rsi_analysis"]
    macd = entry["macd_analysis"]
    bb   = entry["bb_analysis"]
    atr  = entry.get("atr", 0)

    print(
        f"  1m ENTRY   |  Price: {entry['price']:,.2f}  "
        f"|  RSI: {rsi['rsi']:.1f} [{rsi['signal']}]  "
        f"|  MACD: {macd['signal']}  "
        f"|  BB: {bb['position']}  "
        f"|  ATR: {atr:.2f}"
    )

    sig  = signal_data["signal"]
    conf = signal_data["confidence"]
    icon = {"BUY": "▲ BUY", "SELL": "▼ SELL", "NEUTRAL": "● NEUTRAL"}[sig]
    print(f"\n  SIGNAL: {icon}  ({conf})  |  Score: {signal_data['score']}/3")
    print(f"  Reasons: {' | '.join(signal_data['reasons'])}")

def display_stats(trade_log: TradeLogger) -> None:
    s = trade_log.get_statistics()
    if not s or not s.get("total_trades"):
        return
    print(
        f"  STATS  |  Trades: {s['total_trades']}  "
        f"|  Win Rate: {s['win_rate']:.1f}%  "
        f"|  Total P&L: {s['total_profit']:+.2f}  "
        f"|  Profit Factor: {s['profit_factor']:.2f}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN SCAN CYCLE
# ═══════════════════════════════════════════════════════════════════════════

def run_scan(components: Dict, scan_count: int) -> None:
    fetcher   = components["fetcher"]
    executor  = components["executor"]
    pos_mgr   = components["pos_mgr"]
    trade_log = components["trade_log"]
    session_id = components["session_id"]
    indicators = components["indicators"]

    display_header(scan_count)

    # ── Step 1: Fetch & analyse both timeframes ──────────────────────────
    trend_res = analyze_timeframe(
        fetcher, config.TREND_TIMEFRAME, config.TREND_CANDLES,
        indicators, [config.MA_FAST, config.MA_SLOW],
        use_completed_candle=True,
    )
    entry_res = analyze_timeframe(
        fetcher, config.ENTRY_TIMEFRAME, config.ENTRY_CANDLES,
        indicators, [config.MA_FAST, config.MA_SLOW],
        use_completed_candle=False,
    )

    if not trend_res or not entry_res:
        logger.error("Data fetch failed — skipping scan")
        return

    atr_value = entry_res.get("atr") or trend_res.get("atr")
    if atr_value is None or atr_value <= 0:
        logger.error("ATR unavailable — skipping scan")
        return

    # ── Step 2: Account + position status ───────────────────────────────
    summary = pos_mgr.get_position_summary()
    display_account(summary["account"])
    display_positions(summary)

    # ── Step 3: Generate signal ──────────────────────────────────────────
    signal_data = generate_signal(trend_res, entry_res)
    display_signal(signal_data, trend_res, entry_res)

    # ── Step 4: Risk gate ────────────────────────────────────────────────
    print("─" * 68)
    risk = pos_mgr.check_risk_limits()

    trade_log.increment_session_counts(session_id, signal=True)
    action_taken = "SKIPPED"
    block_reason = ""

    if not risk["can_open_new"]:
        block_reason = " | ".join(risk["reasons"])
        print(f"  RISK GATE: BLOCKED  |  {block_reason}")
        action_taken = "BLOCKED"

    elif signal_data["signal"] == "NEUTRAL":
        print("  RISK GATE: PASS  |  No actionable signal — waiting")
        action_taken = "SKIPPED"

    else:
        print(f"  RISK GATE: PASS  |  Executing {signal_data['signal']} ...")
        execution = executor.execute_signal(signal_data, atr_value)

        if execution:
            trade_log.log_trade_open(execution)
            trade_log.increment_session_counts(session_id, trade=True)
            action_taken = "EXECUTED"

            print(
                f"\n  ORDER FILLED\n"
                f"    Ticket:    #{execution['ticket']}\n"
                f"    Direction: {execution['direction']}\n"
                f"    Entry:     {execution['entry_price']:.2f}\n"
                f"    Stop Loss: {execution['stop_loss']:.2f}\n"
                f"    Take Profit: {execution['take_profit']:.2f}\n"
                f"    Volume:    {execution['volume']} lots\n"
                f"    R:R:       {abs(execution['take_profit'] - execution['entry_price']) / abs(execution['entry_price'] - execution['stop_loss']):.2f}:1"
            )
        else:
            print("  EXECUTION FAILED — see logs for detail")
            action_taken = "FAILED"

    # ── Step 5: Log signal for audit trail ───────────────────────────────
    trade_log.log_signal(
        signal_data,
        price=entry_res["price"],
        atr=atr_value,
        action_taken=action_taken,
        block_reason=block_reason,
    )

    # ── Step 6: Session stats ─────────────────────────────────────────────
    display_stats(trade_log)


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    components = initialize()
    fetcher    = components["fetcher"]
    trade_log  = components["trade_log"]
    session_id = components["session_id"]

    scan_count = 0
    start_time = time.time()

    try:
        while True:
            scan_count += 1
            cycle_start = time.time()

            try:
                run_scan(components, scan_count)
            except Exception as e:
                logger.error(f"Scan error (non-fatal): {e}")
                traceback.print_exc()

            if config.RUN_ONCE:
                print("\n  RUN_ONCE mode — exiting after first scan.")
                break

            elapsed    = time.time() - cycle_start
            sleep_time = max(0, config.SCAN_INTERVAL - elapsed)
            print("=" * 68)
            print(f"  Sleeping {sleep_time:.0f}s  |  Next scan at "
                  f"{(datetime.now() + timedelta(seconds=sleep_time)).strftime('%H:%M:%S')}"
                  f"  |  Ctrl+C to stop")

            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\n  STOPPING BOT...")

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        traceback.print_exc()

    finally:
        # ── Shutdown summary ─────────────────────────────────────────────
        duration = time.time() - start_time
        account  = fetcher.get_account_info()

        if account:
            trade_log.end_session(session_id, account["balance"])

        stats = trade_log.get_statistics()

        print("\n" + "=" * 68)
        print("  SESSION SUMMARY")
        print(f"  Runtime:      {timedelta(seconds=int(duration))}")
        print(f"  Total Scans:  {scan_count}")
        if account:
            print(f"  Final Balance: {account['balance']:,.2f} {account['currency']}")
            print(f"  Final Equity:  {account['equity']:,.2f}")
        if stats and stats.get("total_trades"):
            print(f"  Trades:       {stats['total_trades']}")
            print(f"  Win Rate:     {stats['win_rate']:.1f}%")
            print(f"  Net P&L:      {stats['total_profit']:+.2f}")
            print(f"  Profit Factor:{stats['profit_factor']:.2f}")
        print("=" * 68)

        fetcher.disconnect()
        trade_log.close()
        logger.info("Bot shutdown complete.")


if __name__ == "__main__":
    main()
