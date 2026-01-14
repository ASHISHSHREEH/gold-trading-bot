"""
GOLD TRADING BOT - INTEGRATED SYSTEM (MAIN)
===========================================
A fully automated paper trading system that combines:
1. Multi-Timeframe Analysis (1H Trend + 1M Entry)
2. Robust Risk Management
3. Real-time Position Monitoring (SL/TP)
4. Database Persistence

Execution Cycle:
Fetch Data -> Update Positions -> Check Risk -> Analyze -> Generate Signal -> Execute
"""

import sys
import time
import logging
import traceback
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# --- CUSTOM MODULES ---
from database.schema import TradingDatabase
from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager
from trading.trade_executor import TradeExecutor
from data.fetcher import GoldDataFetcher

# Indicators
from indicators.rsi import RSICalculator
from indicators.macd import MACDCalculator
from indicators.bollinger import BollingerBandsCalculator
from indicators.moving_average import MovingAverageCalculator

# --- CONFIGURATION CONSTANTS ---
ACCOUNT_SIZE = 1_000_000      # Starting balance (JPY)
RISK_PER_TRADE = 0.02         # 2% risk per trade
MAX_DAILY_LOSS = 0.05         # 5% max daily loss
MAX_POSITIONS = 3             # Max concurrent positions
SCAN_INTERVAL = 300           # Seconds between scans
RUN_ONCE = False              # Set True for testing/debugging

TIMEFRAMES = {
    'trend': {
        'name': '1-Hour Trend',
        'interval': '1h',
        'period': '1mo',
        'ma_periods': [50, 200]
    },
    'entry': {
        'name': '1-Minute Entry',
        'interval': '1m',
        'period': '5d',
        'ma_periods': [20, 50]
    }
}

# --- LOGGING CONFIGURATION ---
if not os.path.exists('logs'):
    os.makedirs('logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot_integrated.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("GoldBot")

# --- INITIALIZATION FUNCTIONS ---

def initialize_components() -> Dict[str, Any]:
    """
    Initialize all trading components at startup.
    Returns a dictionary containing all instances.
    """
    print("🤖 INITIALIZING INTEGRATED TRADING SYSTEM...")
    logger.info("System startup initiated.")

    try:
        # 1. Database
        db = TradingDatabase("data/trading.db")
        logger.info("Database connected.")

        # 2. Managers
        pos_mgr = PositionManager(db)
        risk_mgr = RiskManager(
            account_size=ACCOUNT_SIZE,
            max_risk_per_trade=RISK_PER_TRADE,
            max_daily_loss=MAX_DAILY_LOSS,
            max_positions=MAX_POSITIONS
        )
        logger.info("Managers initialized.")

        # 3. Executor
        executor = TradeExecutor(db, risk_mgr, pos_mgr)
        logger.info("Trade Executor ready.")

        # 4. Data Fetcher
        fetcher = GoldDataFetcher()
        logger.info("Data Fetcher connected.")

        # 5. Indicators
        indicators = {
            'rsi': RSICalculator(period=14),
            'macd': MACDCalculator(),
            'bb': BollingerBandsCalculator(period=20, std_dev=2),
            'ma': MovingAverageCalculator()
        }
        logger.info("Technical Indicators loaded.")

        print("✅ ALL SYSTEMS READY!")
        
        return {
            'db': db,
            'pos_mgr': pos_mgr,
            'risk_mgr': risk_mgr,
            'executor': executor,
            'fetcher': fetcher,
            'indicators': indicators
        }

    except Exception as e:
        logger.critical(f"Initialization Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

# --- ANALYSIS FUNCTIONS ---

def analyze_timeframe(fetcher, tf_config: Dict, indicators: Dict, use_completed_candle: bool = False) -> Optional[Dict]:
    """
    Analyze a single timeframe (Fetch -> Calculate -> Extract Latest).
    
    Args:
        use_completed_candle (bool): 
            If True (Trend), uses iloc[-2] (last closed candle). 
            If False (Entry), uses iloc[-1] (current live candle).
    """
    tf_name = tf_config['name']
    
    try:
        # a) Fetch Data
        df = fetcher.get_historical_data(
            period=tf_config['period'],
            interval=tf_config['interval']
        )
        
        if df.empty:
            logger.warning(f"No data received for {tf_name}")
            return None

        # Safety Check: Ensure enough data for indicators (Max MA period + buffer)
        min_required = max(tf_config['ma_periods']) + 5
        if len(df) < min_required:
            logger.warning(f"Insufficient data for {tf_name}. Got {len(df)}, need {min_required}")
            return None

        # b) Determine Target Index (Anti-Repainting Logic)
        target_index = -2 if use_completed_candle else -1
        
        # c) Calculate Indicators (Pass full DF, extracting specific index later)
        # Moving Averages
        ma_df = indicators['ma'].calculate_multiple_mas(df['close'], periods=tf_config['ma_periods'])
        df = df.join(ma_df)
        
        # Other indicators
        df['rsi'] = indicators['rsi'].calculate_rsi(df)
        macd_df = indicators['macd'].calculate_macd(df)
        df = df.join(macd_df)
        bb_df = indicators['bb'].calculate_bands(df['close'])
        df = df.join(bb_df)

        # d) Slice DataFrame for Analysis
        # CRITICAL: Slicing logic prevents "IndexError: slice(None, 0, None)" when target_index is -1
        if target_index == -1:
            analysis_slice = df
            ma_slice = ma_df
            macd_slice = macd_df
            bb_slice = bb_df
        else:
            # slice up to target_index+1 because Python slice end is exclusive
            # e.g., if target is -2, we want ...,-3,-2. slice [:-1] gives that.
            analysis_slice = df.iloc[:target_index+1]
            ma_slice = ma_df.iloc[:target_index+1]
            macd_slice = macd_df.iloc[:target_index+1]
            bb_slice = bb_df.iloc[:target_index+1]

        # e) Run Analysis methods
        ma_ana = indicators['ma'].analyze_latest(analysis_slice['close'], ma_slice)
        rsi_ana = indicators['rsi'].analyze_latest(analysis_slice)
        macd_ana = indicators['macd'].analyze_latest(macd_slice)
        bb_ana = indicators['bb'].analyze_latest(analysis_slice['close'], bb_slice)

        return {
            'price': df['close'].iloc[target_index],
            'timestamp': df.index[target_index],
            'ma_analysis': ma_ana,
            'rsi_analysis': rsi_ana,
            'macd_analysis': macd_ana,
            'bb_analysis': bb_ana,
            'ma_fast': ma_ana['ma_fast'],
            'ma_slow': ma_ana['ma_slow']
        }

    except Exception as e:
        logger.error(f"Error analyzing {tf_name}: {e}")
        return None

def generate_signal(trend_result: Dict, entry_result: Dict) -> Dict[str, Any]:
    """
    Generate BUY/SELL/NEUTRAL signal based on Multi-Timeframe Confluence.
    Rule: Trade in direction of 1H Trend ONLY if 1M Entry signals confirm.
    """
    signal = "NEUTRAL"
    confidence = "LOW"
    reasons = []
    
    # 1. Extract Trend Direction
    trend_dir = trend_result['ma_analysis']['trend'] # STRONG_BULL, BULL, BEAR, etc.
    is_bullish_trend = trend_dir in ['STRONG_BULL', 'BULL']
    is_bearish_trend = trend_dir in ['STRONG_BEAR', 'BEAR']
    
    reasons.append(f"1h trend: {trend_dir}")

    # 2. Analyze Entry Signals
    rsi = entry_result['rsi_analysis']
    macd = entry_result['macd_analysis']
    bb = entry_result['bb_analysis']
    
    score = 0
    
    # BULLISH LOGIC
    if is_bullish_trend:
        # RSI Condition: Oversold or Neutral-Rising (Not Overbought)
        if rsi['signal'] == 'BUY': 
            score += 1
            reasons.append(f"RSI oversold ({rsi['rsi']:.1f})")
        
        # MACD Condition
        if macd['signal'] == 'BUY': 
            score += 1
            reasons.append("MACD bullish")
            
        # BB Condition
        if bb['position'] in ['NEAR_LOWER', 'BELOW_LOWER', 'WALKING_UP']:
            score += 1
            reasons.append("BB near lower band")
            
        # Decision
        if score >= 2:
            signal = "BUY"
    
    # BEARISH LOGIC
    elif is_bearish_trend:
        # RSI Condition
        if rsi['signal'] == 'SELL': 
            score += 1
            reasons.append(f"RSI overbought ({rsi['rsi']:.1f})")
            
        # MACD Condition
        if macd['signal'] == 'SELL': 
            score += 1
            reasons.append("MACD bearish")
            
        # BB Condition
        if bb['position'] in ['NEAR_UPPER', 'ABOVE_UPPER', 'WALKING_DOWN']:
            score += 1
            reasons.append("BB near upper band")
            
        # Decision
        if score >= 2:
            signal = "SELL"

    # 3. Determine Confidence
    if score >= 3:
        confidence = "HIGH"
    elif score == 2:
        confidence = "MODERATE"
    else:
        confidence = "LOW"
        if signal != "NEUTRAL": 
            reasons.append("Low indicator confluence")
            signal = "NEUTRAL" # Filter out low confidence

    return {
        'signal': signal,
        'confidence': confidence,
        'reasons': reasons,
        'trend': trend_result['ma_analysis'],
        'entry_analysis': entry_result
    }

# --- DISPLAY FUNCTIONS ---

def display_scan_header(scan_count: int):
    print("=" * 68)
    print(f"📡 SCAN #{scan_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def display_portfolio(pos_mgr):
    port = pos_mgr.db.get_portfolio()
    if not port: return
    
    pnl_sign = "+" if port['unrealized_pnl'] >= 0 else ""
    real_sign = "+" if port['realized_pnl'] >= 0 else ""
    
    # Calculate daily % change roughly
    pct_change = ((port['equity'] - ACCOUNT_SIZE) / ACCOUNT_SIZE) * 100
    pct_sign = "+" if pct_change >= 0 else ""

    print(f"💰 PORTFOLIO STATUS")
    print(f"Balance:     ¥{port['balance']:,.2f}")
    print(f"Equity:      ¥{port['equity']:,.2f} ({pct_sign}{pct_change:.2f}%)")
    print(f"Unrealized:  {pnl_sign}¥{port['unrealized_pnl']:,.2f}")
    print(f"Realized:    {real_sign}¥{port['realized_pnl']:,.2f}")
    print(f"Free Margin: ¥{port['free_margin']:,.2f}")

def display_positions(pos_mgr):
    summary = pos_mgr.get_position_summary()
    positions = summary['positions']
    count = summary['count']
    
    status_icon = "⚠️ FULL" if count >= MAX_POSITIONS else "✅"
    
    print(f"📊 OPEN POSITIONS ({count}/{MAX_POSITIONS}) {status_icon}")
    
    if count == 0:
        print("No open positions")
    else:
        for pos in positions:
            pnl = pos['unrealized_pnl']
            sign = "+" if pnl >= 0 else ""
            print(f"#{pos['id']} | {pos['direction']:<5} {pos['symbol']} @ {pos['entry_price']:.2f} | "
                  f"Current: {pos['current_price']:.2f} | P&L: {sign}¥{pnl:.2f} | "
                  f"SL: {pos['stop_loss']:.1f} | TP: {pos['take_profit']:.1f}")

def display_recent_trades(db, limit=3):
    trades = db.get_trade_history(limit=limit)
    print(f"📈 RECENT CLOSED TRADES (Last {limit})")
    
    if not trades:
        print("No trades yet")
    else:
        for t in trades:
            icon = "✅" if t['pnl'] > 0 else "❌"
            pnl_sign = "+" if t['pnl'] >= 0 else ""
            pct_sign = "+" if t['pnl_percent'] >= 0 else ""
            
            print(f"{icon} #{t['id']}: {t['direction']:<5} @ {t['entry_price']:.0f} → {t['exit_price']:.0f} | "
                  f"P&L: {pnl_sign}¥{t['pnl']:.2f} ({pct_sign}{t['pnl_percent']:.1f}%) | {t['exit_reason']}")

def display_signal_analysis(signal_data, trend_res, entry_res):
    t_ana = trend_res['ma_analysis']
    e_ana = entry_res
    
    print("──────────────────────────────────────────────────────────────────")
    print(f"🕐 1-HOUR TREND (CONFIRMED @ {trend_res['timestamp'].strftime('%H:%M')})")
    print(f"Direction: {t_ana['trend']}")
    print(f"MA Fast:   ¥{t_ana['ma_fast']:,.2f}")
    print(f"MA Slow:   ¥{t_ana['ma_slow']:,.2f}")
    
    print(f"⚡ 1-MINUTE ENTRY (LIVE @ {entry_res['timestamp'].strftime('%H:%M:%S')})")
    print(f"Price:  ¥{entry_res['price']:,.2f}")
    
    # Indicators
    rsi = e_ana['rsi_analysis']
    macd = e_ana['macd_analysis']
    bb = e_ana['bb_analysis']
    
    print(f"RSI:    {rsi['rsi']:.2f} → {rsi['signal']}")
    print(f"MACD:   {macd['signal']}")
    print(f"BB:     {bb['position']}")
    
    # Final Result
    sig = signal_data['signal']
    conf = signal_data['confidence']
    color = "🟢" if sig == 'BUY' else ("🔴" if sig == 'SELL' else "⚪")
    
    print(f"{color} FINAL SIGNAL: {sig} ({conf})")
    print(f"Reasons: {'; '.join(signal_data['reasons'])}")

# --- MAIN SCAN LOGIC ---

def run_scan(components: Dict, scan_count: int):
    """
    Execute one complete scan cycle.
    """
    db = components['db']
    pos_mgr = components['pos_mgr']
    risk_mgr = components['risk_mgr']
    executor = components['executor']
    fetcher = components['fetcher']
    indicators = components['indicators']

    display_scan_header(scan_count)

    try:
        # Step 2: Fetch and Analyze
        print("📊 Fetching market data...")
        
        # Trend (1H) - Use Completed Candle (Anti-Repainting)
        trend_res = analyze_timeframe(fetcher, TIMEFRAMES['trend'], indicators, use_completed_candle=True)
        
        # Entry (1M) - Use Current Candle (Tactical)
        entry_res = analyze_timeframe(fetcher, TIMEFRAMES['entry'], indicators, use_completed_candle=False)

        if not trend_res or not entry_res:
            logger.error("Failed to analyze timeframes. Skipping scan.")
            return

        current_price = entry_res['price']
        print(f"✅ Current Price: ¥{current_price:,.2f}")

        # Step 4: UPDATE EXISTING POSITIONS FIRST (CRITICAL)
        print("🔄 Updating open positions...")
        update_res = pos_mgr.update_all_positions({'XAU_JPY': current_price})
        print(f"Updated: {update_res['updated']} | Closed: {update_res['closed']}")
        
        # Log closures if any
        for hit in update_res['stop_loss_hits']:
            logger.warning(f"Stop Loss Hit during scan: {hit}")
        for hit in update_res['take_profit_hits']:
            logger.info(f"Take Profit Hit during scan: {hit}")

        # Step 5: Display Status
        display_portfolio(pos_mgr)
        display_positions(pos_mgr)
        display_recent_trades(db)

        # Step 6: Check Risk Limits
        print("──────────────────────────────────────────────────────────────────")
        risk_check = pos_mgr.check_risk_limits(max_positions=MAX_POSITIONS, max_loss_pct=MAX_DAILY_LOSS)
        
        # Step 7: Generate Signal
        signal_data = generate_signal(trend_res, entry_res)
        
        # Step 8: Display Analysis
        display_signal_analysis(signal_data, trend_res, entry_res)

        # Step 9: Execute Trade
        print("🛡️ RISK CHECK")
        if not risk_check['can_open_new']:
            print(f"⚠️ Cannot trade: {'; '.join(risk_check['reasons'])}")
        elif signal_data['signal'] == "NEUTRAL":
            print("⚪ No actionable signal.")
        else:
            print(f"✅ All checks passed - EXECUTING {signal_data['signal']}")
            
            execution = executor.execute_signal(
                signal_data=signal_data,
                current_price=current_price,
                symbol="XAU_JPY"
            )
            
            if execution:
                print("🎉 POSITION OPENED!")
                print(f"ID: #{execution['position_id']}")
                print(f"Direction: {execution['direction']}")
                print(f"Entry: ¥{execution['entry_price']:,.2f}")
                print(f"SL: ¥{execution['stop_loss']:,.2f} | TP: ¥{execution['take_profit']:,.2f}")
                print(f"Size: {execution['size']:.4f} units")
                print(f"Risk: ¥{execution['risk_amount']:,.2f} | Reward: ¥{execution['reward_potential']:,.2f}")
                print(f"R:R: {execution['rr_ratio']:.2f}:1")
            else:
                print("❌ Execution failed (See logs for details)")

    except Exception as e:
        logger.error(f"Error during scan: {e}")
        traceback.print_exc()

# --- ENTRY POINT ---

def main():
    print("\n" * 2)
    print("****************************************************************")
    print("* GOLD TRADING BOT - INTEGRATED SYSTEM v1.0                    *")
    print("* Multi-Timeframe | Risk Managed | SQLite                      *")
    print("****************************************************************")
    print("\n")

    components = initialize_components()
    db = components['db']
    
    scan_count = 0
    start_time = time.time()

    try:
        while True:
            scan_count += 1
            cycle_start = time.time()
            
            run_scan(components, scan_count)
            
            if RUN_ONCE:
                print("\n🏁 Run Once mode enabled. Exiting.")
                break
                
            # Smart Sleep
            elapsed = time.time() - cycle_start
            sleep_time = max(0, SCAN_INTERVAL - elapsed)
            print("=" * 68)
            print(f"💤 Sleeping {sleep_time:.1f}s until next scan... (Press Ctrl+C to stop)")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\n🛑 STOPPING BOT...")
        
        # Final Summary
        duration = time.time() - start_time
        port = db.get_portfolio()
        stats = db.get_statistics()
        
        print("\n📊 SESSION SUMMARY")
        print(f"Runtime:      {timedelta(seconds=int(duration))}")
        print(f"Total Scans:  {scan_count}")
        print(f"Final Equity: ¥{port['equity']:,.2f}")
        print(f"Total Trades: {stats.get('total_trades', 0)}")
        print(f"Win Rate:     {stats.get('win_rate', 0):.1f}%")
        print("Goodbye! 👋")

    except Exception as e:
        logger.critical(f"Fatal Error: {e}")
        traceback.print_exc()
        
    finally:
        db.close()
        logger.info("System shutdown.")

if __name__ == "__main__":
    main()