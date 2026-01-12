"""
Gold Trading Bot - Professional Multi-Timeframe Edition
Core Logic:
1. 1-Hour Trend Filter (Uses COMPLETED candles to prevent repainting)
2. 1-Minute Entry Signal (Tactical entry)
3. Robust Risk Management & Trade Logging
"""

import sys
import time
import logging
import traceback
import pandas as pd
from datetime import datetime

# --- CUSTOM MODULES ---
from data.fetcher import GoldDataFetcher
from indicators.rsi import RSICalculator
from indicators.macd import MACDCalculator
from indicators.bollinger import BollingerBandsCalculator
from indicators.moving_average import MovingAverageCalculator
from trading.risk_manager import RiskManager
from trading.trade_logger import TradeLogger

# --- CONFIGURATION ---
ACCOUNT_SIZE = 1_000_000   # JPY
RISK_PER_TRADE = 0.02      # 2% Risk
MAX_DAILY_LOSS = 0.05      # 5% Max daily loss
SCAN_INTERVAL = 60         # Seconds between scans
RUN_ONCE = False           # Set True for testing/single execution

# Timeframe Settings
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

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def analyze_timeframe(fetcher, tf_config, tools, use_completed_candle=False):
    """
    Analyze a timeframe with Anti-Repainting Logic.
    
    Args:
        use_completed_candle (bool): CRITICAL PARAMETER.
            - If True: Uses iloc[-2] (last closed candle). Essential for Trend Analysis.
            - If False: Uses iloc[-1] (current forming candle). Acceptable for Entries.
    """
    tf_name = tf_config['name']
    
    # 1. Fetch Data
    df = fetcher.get_historical_data(
        period=tf_config['period'],
        interval=tf_config['interval']
    )
    
    if df.empty:
        logger.error(f"No data received for {tf_name}")
        return {'error': 'No data'}

    # 2. Calculate Indicators
    ma_df = tools['ma'].calculate_multiple_mas(df['close'], periods=tf_config['ma_periods'])
    df = df.join(ma_df)
    
    df['rsi'] = tools['rsi'].calculate_rsi(df)
    macd_df = tools['macd'].calculate_macd(df)
    df = df.join(macd_df)
    bb_df = tools['bb'].calculate_bands(df['close'])
    df = df.join(bb_df)

    # 3. Select Candle Index (Anti-Repainting Logic)
    # iloc[-1] is the current, incomplete candle (Prone to repainting)
    # iloc[-2] is the last fully completed candle (Confirmed data)
    target_index = -2 if use_completed_candle else -1
    
    candle_time = df.index[target_index]
    current_price = df['close'].iloc[target_index]
    
    status = "CONFIRMED/CLOSED" if use_completed_candle else "LIVE/FORMING"

    # 4. Run Analysis on the Selected Index
    # BUG FIX: Correctly slice the dataframe for historical analysis
    if target_index == -1:
        # Use entire dataframe (current candle is the last one)
        analysis_df = df.copy()
        ma_analysis_df = ma_df.copy()
        macd_analysis_df = macd_df.copy()
        bb_analysis_df = bb_df.copy()
    else:
        # Slice up to the target index (inclusive)
        # In Python slicing [0:x], x is exclusive. 
        # So to get index -2, we slice [:-1].
        analysis_df = df.iloc[:target_index+1]
        ma_analysis_df = ma_df.iloc[:target_index+1]
        macd_analysis_df = macd_df.iloc[:target_index+1]
        bb_analysis_df = bb_df.iloc[:target_index+1]
    
    ma_ana = tools['ma'].analyze_latest(analysis_df['close'], ma_analysis_df)
    rsi_ana = tools['rsi'].analyze_latest(analysis_df)
    macd_ana = tools['macd'].analyze_latest(macd_analysis_df)
    bb_ana = tools['bb'].analyze_latest(analysis_df['close'], bb_analysis_df)

    ma_fast_col = f"ma_{tf_config['ma_periods'][0]}"
    ma_slow_col = f"ma_{tf_config['ma_periods'][1]}"

    return {
        'timestamp': candle_time,
        'status': status,
        'price': current_price,
        'ma_analysis': ma_ana,
        'rsi_analysis': rsi_ana,
        'macd_analysis': macd_ana,
        'bb_analysis': bb_ana,
        'ma_values': {
            'fast': df[ma_fast_col].iloc[target_index],
            'slow': df[ma_slow_col].iloc[target_index]
        }
    }

def generate_signal(trend_data, entry_data):
    """Combine Higher Timeframe Trend with Lower Timeframe Entry."""
    trend = trend_data['ma_analysis']['trend']
    entry_rsi = entry_data['rsi_analysis']
    entry_macd = entry_data['macd_analysis']
    entry_bb = entry_data['bb_analysis']
    
    signal = "NEUTRAL"
    confidence = "LOW"
    reasons = []

    # Direction Bias from 1H Trend
    is_bullish_trend = trend in ['BULL', 'STRONG_BULL']
    is_bearish_trend = trend in ['BEAR', 'STRONG_BEAR']
    
    reasons.append(f"1H Trend: {trend} (Confirmed)")

    # LOGIC: Trend Following
    if is_bullish_trend:
        # Look for Buys on 1m
        score = 0
        if entry_rsi['signal'] == 'BUY': score += 1
        if entry_macd['signal'] == 'BUY': score += 1
        if entry_bb['signal'] in ['BUY', 'BUY_TREND']: score += 1
        
        if score >= 2:
            signal = "BUY"
            confidence = "HIGH" if score == 3 else "MODERATE"
            reasons.append(f"1M Entry: {score}/3 Indicators Bullish")

    elif is_bearish_trend:
        # Look for Sells on 1m
        score = 0
        if entry_rsi['signal'] == 'SELL': score += 1
        if entry_macd['signal'] == 'SELL': score += 1
        if entry_bb['signal'] in ['SELL', 'SELL_TREND']: score += 1
        
        if score >= 2:
            signal = "SELL"
            confidence = "HIGH" if score == 3 else "MODERATE"
            reasons.append(f"1M Entry: {score}/3 Indicators Bearish")
    
    return {
        'signal': signal,
        'confidence': confidence,
        'direction': 'LONG' if signal == 'BUY' else ('SHORT' if signal == 'SELL' else 'NONE'),
        'reasons': "; ".join(reasons),
        'main_trend': trend  # BUG FIX: Passing trend explicitly for logger
    }

def execute_trade_logic(signal_data, entry_data, risk_mgr, trade_logger):
    """Calculates parameters, validates risk, and logs trade."""
    if signal_data['signal'] == "NEUTRAL":
        return None

    current_price = entry_data['price']
    direction = signal_data['direction']
    
    # 1. Calculate Dynamic Stop Loss based on Volatility (BB Bandwidth)
    volatility = entry_data['bb_analysis']['bandwidth'] * current_price
    
    # Fallback if volatility is near zero
    if volatility < (current_price * 0.0005): 
        volatility = current_price * 0.001 

    if direction == 'LONG':
        stop_loss = current_price - (volatility * 1.5)
        take_profit = current_price + (volatility * 3.0) 
    else:
        stop_loss = current_price + (volatility * 1.5)
        take_profit = current_price - (volatility * 3.0)

    # 2. Calculate Position Size
    size = risk_mgr.calculate_position_size(
        ACCOUNT_SIZE, RISK_PER_TRADE, current_price, stop_loss
    )

    # 3. Validate Trade (R:R Check)
    validation = risk_mgr.validate_trade(current_price, stop_loss, take_profit)

    if validation['valid']:
        # 4. Construct Trade Record
        trade_record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "signal": signal_data['signal'],
            "confidence": signal_data['confidence'],
            "direction": direction,
            "entry": round(current_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "size": round(size, 4),
            "risk_amount": round(validation['risk_amount'], 2),
            "reward_potential": round(validation['reward_amount'], 2),
            "rr_ratio": validation['rr_ratio'],
            "trend": signal_data['main_trend'], # BUG FIX: Uses corrected trend source
            "reason": signal_data['reasons']
        }
        
        # 5. Log Trade
        if trade_logger.log_trade(trade_record):
            logger.info(f"✅ TRADE EXECUTED & LOGGED: {direction} @ {current_price}")
            return trade_record
    else:
        logger.warning(f"⛔ Trade Rejected by Risk Manager: {validation['reason']}")
        return None

def print_status(scan_count, trend_res, entry_res, signal_res):
    """Clean console output."""
    print("\n" + "="*60)
    print(f"📡 SCAN #{scan_count} | {datetime.now().strftime('%H:%M:%S')}")
    print("="*60)
    
    # Trend Section
    t_ts = trend_res['timestamp'].strftime('%H:%M')
    print(f"🕐 1-HOUR TREND ({trend_res['status']} @ {t_ts})")
    print(f"   Structure: {trend_res['ma_analysis']['trend']}")
    print(f"   MA Alignment: Fast={trend_res['ma_values']['fast']:.2f} | Slow={trend_res['ma_values']['slow']:.2f}")
    
    # Entry Section
    e_ts = entry_res['timestamp'].strftime('%H:%M:%S')
    print(f"\n⚡ 1-MINUTE ENTRY ({entry_res['status']} @ {e_ts})")
    print(f"   Price: ¥{entry_res['price']:.2f}")
    print(f"   RSI:   {entry_res['rsi_analysis']['rsi']:.2f}")
    print(f"   MACD:  {entry_res['macd_analysis']['signal']}")
    
    # Signal Section
    color = "🟢" if signal_res['signal'] == 'BUY' else ("🔴" if signal_res['signal'] == 'SELL' else "⚪")
    print(f"\n{color} DECISION: {signal_res['signal']} ({signal_res['confidence']})")
    print(f"   Reason: {signal_res['reasons']}")
    print("="*60)

def main():
    print("🤖 GOLD BOT INITIALIZING...")
    
    try:
        fetcher = GoldDataFetcher()
        risk_mgr = RiskManager(ACCOUNT_SIZE, RISK_PER_TRADE, MAX_DAILY_LOSS)
        trade_logger = TradeLogger()
        
        tools = {
            'rsi': RSICalculator(14),
            'macd': MACDCalculator(),
            'bb': BollingerBandsCalculator(20, 2),
            'ma': MovingAverageCalculator()
        }
        logger.info("Modules loaded successfully.")
        
    except Exception as e:
        logger.critical(f"Initialization Failed: {e}")
        return

    # Main Execution Loop
    scan_count = 0
    
    try:
        while True:
            scan_count += 1
            start_time = time.time()
            
            try:
                # A. Analyze Trend (ANTI-REPAINTING: use_completed_candle=True)
                trend_res = analyze_timeframe(
                    fetcher, TIMEFRAMES['trend'], tools, use_completed_candle=True
                )
                
                # B. Analyze Entry (Tactical: use_completed_candle=False for speed)
                entry_res = analyze_timeframe(
                    fetcher, TIMEFRAMES['entry'], tools, use_completed_candle=False
                )
                
                if 'error' in trend_res or 'error' in entry_res:
                    logger.warning("Data fetch error. Retrying next cycle.")
                    time.sleep(10)
                    continue

                # C. Generate Signal
                signal_res = generate_signal(trend_res, entry_res)
                
                # D. Print Feedback
                print_status(scan_count, trend_res, entry_res, signal_res)
                
                # E. Execute & Log
                if signal_res['signal'] != "NEUTRAL":
                    execute_trade_logic(signal_res, entry_res, risk_mgr, trade_logger)
                
                # Check Run Mode
                if RUN_ONCE:
                    print("\n🏁 Test Run Complete.")
                    break
                
                # Smart Sleep
                elapsed = time.time() - start_time
                sleep_time = max(0, SCAN_INTERVAL - elapsed)
                print(f"💤 Sleeping {sleep_time:.1f}s...")
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                traceback.print_exc()
                time.sleep(30) 

    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
        summary = trade_logger.get_trade_summary()
        print("\n📊 SESSION SUMMARY:")
        print(summary)

if __name__ == "__main__":
    main()