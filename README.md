# 🤖 Gold Trading Bot - Professional Edition

AI-powered multi-timeframe gold (XAU/JPY) trading bot with advanced technical analysis, risk management, and anti-repainting protection.

## 🎯 Project Status
✅ **Phase 1 COMPLETE** - Production-ready trading system with all indicators
🚀 **Phase 2 NEXT** - Paper trading system with virtual portfolio

## ✨ Features

### ✅ Implemented
- ✅ **Multi-Timeframe Analysis**
  - 1-hour trend filter (uses completed candles - no repainting!)
  - 1-minute entry signals (tactical entries)
  - Confluence logic (requires 2+ indicators to agree)

- ✅ **Technical Indicators Suite**
  - RSI (Relative Strength Index) with overbought/oversold detection
  - MACD (Moving Average Convergence Divergence) with histogram
  - Bollinger Bands with squeeze detection
  - Moving Averages (50 & 200 period) with Golden/Death Cross detection

- ✅ **Risk Management System**
  - Dynamic position sizing (2% risk per trade)
  - Automatic stop loss calculation
  - Take profit based on R:R ratio (minimum 2:1)
  - Daily loss limits (5% max)
  - Maximum concurrent positions (3 trades)

- ✅ **Data Pipeline**
  - yfinance for historical OHLCV data (FREE, no API key needed)
  - MetalPriceAPI for current spot prices
  - Hybrid approach for best data quality

- ✅ **Production Features**
  - Anti-repainting protection (uses completed candles for trend)
  - Continuous execution loop with configurable scan interval
  - Trade logging to CSV
  - File + console logging
  - Comprehensive error handling
  - Smart sleep (adjusts for processing time)

### 🔄 Coming Next (Option B)
- 🔄 Paper trading system with virtual portfolio
- 🔄 SQLite database for trade history
- 🔄 Position manager for tracking open trades
- 🔄 Performance analytics (win rate, profit factor, Sharpe ratio)
- 🔄 Backtesting engine for historical simulation
- 🔄 Dashboard for portfolio visualization

## 🚀 Quick Start

### Prerequisites
- Python 3.11 or higher
- Git

### Installation
```bash
# Clone repository
git clone https://github.com/ASHISHSHREEH/gold-trading-bot.git
cd gold-trading-bot

# Install dependencies
pip install -r requirements.txt
```

### Configuration
```bash
# Create .env file
cp .env.example .env

# Edit .env (optional - only needed for MetalPriceAPI)
notepad .env
```

Add MetalPriceAPI key (optional - bot works without it):
```env
METALPRICE_API_KEY=your_key_here
```

### Running the Bot
```bash
# Test mode (single scan)
python test_bot.py

# Production mode (continuous loop)
python main.py
```

Press `Ctrl+C` to stop the bot.

## 📊 How It Works

### Multi-Timeframe Strategy
```
1. 1-HOUR TIMEFRAME (Trend Filter)
   └─> Uses COMPLETED candle (anti-repainting)
   └─> Calculates 50 & 200 period MAs
   └─> Determines trend: STRONG_BULL, BULL, NEUTRAL, BEAR, STRONG_BEAR
   └─> Detects Golden/Death Cross

2. 1-MINUTE TIMEFRAME (Entry Signal)
   └─> Uses current candle for precise entries
   └─> RSI: Oversold (<30) or Overbought (>70)
   └─> MACD: Bullish or Bearish momentum
   └─> Bollinger Bands: Price at support/resistance

3. CONFLUENCE LOGIC
   └─> BUY: 1h bullish trend + 2+ bullish 1m signals
   └─> SELL: 1h bearish trend + 2+ bearish 1m signals
   └─> NEUTRAL: Conflicting signals → WAIT (safe!)

4. RISK MANAGEMENT
   └─> Calculate position size (2% account risk)
   └─> Set stop loss (volatility-based)
   └─> Set take profit (3:1 R:R minimum)
   └─> Validate trade before execution
```

## 🏗️ Project Structure
```
gold-trading-bot/
├── data/
│   └── fetcher.py              # Hybrid data fetcher (yfinance + MetalPriceAPI) ✅
├── indicators/
│   ├── rsi.py                  # RSI calculator ✅
│   ├── macd.py                 # MACD calculator ✅
│   ├── bollinger.py            # Bollinger Bands calculator ✅
│   └── moving_average.py       # MA calculator with Golden/Death Cross ✅
├── trading/
│   ├── risk_manager.py         # Risk management system ✅
│   └── trade_logger.py         # Trade logging to CSV ✅
├── logs/
│   ├── trade_history.csv       # Trade log (auto-created)
│   └── bot.log                 # Application log (auto-created)
├── main.py                     # Main bot with multi-timeframe logic ✅
├── test_bot.py                 # Test script (single scan) ✅
├── .env                        # Your API keys (NOT in Git)
├── .env.example                # Template (safe to commit)
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## 🛡️ Anti-Repainting Protection

**Critical Fix Implemented:**
```python
# WRONG (Repainting bug):
current_price = df['close'].iloc[-1]  # Uses forming candle!
# At 10:15 AM → sees incomplete 10:00-11:00 candle
# Price spikes → bot enters
# By 10:59 AM → candle closes red (repaints!)

# CORRECT (Anti-repainting):
current_price = df['close'].iloc[-2]  # Uses completed candle!
# At 10:15 AM → sees completed 9:00-10:00 candle
# No repainting possible!
```

The bot uses **completed candles** for trend analysis to prevent false signals.

## 📈 Example Output
```
====================================================================
   📡 SCAN #1 | 2026-01-13 12:34:56
====================================================================

   🕐 1-HOUR TREND (CONFIRMED/CLOSED)
      Candle Time: 2026-01-13 10:00
      Price:       ¥4,602.40
      Trend:       STRONG_BULL
      MA Fast/Slow: ¥4,520.05 / ¥4,440.98

   ⚡ 1-MINUTE ENTRY (LIVE/FORMING)
      Time:  12:34:56
      Price: ¥4,625.90
      RSI:   28.50 → BUY
      MACD:  BUY (MODERATE)
      BB:    NEAR_LOWER

   🟢 FINAL SIGNAL: BUY (HIGH)
      1H Trend: STRONG_BULL (Confirmed); 1M Entry: 3/3 Indicators Bullish
====================================================================

✅ TRADE EXECUTED & LOGGED: LONG @ 4625.90
   Stop Loss:   ¥4,595.23
   Take Profit: ¥4,717.91
   Position:    2.8571 units
   Risk:        ¥20,000
   Reward:      ¥60,000
   R:R Ratio:   3.00:1
```

## 🧪 Testing

### Test Mode (Single Scan)
```bash
python test_bot.py
```

### Continuous Mode
```bash
python main.py
```

Set `RUN_ONCE = True` in `main.py` for testing.

## 📊 View Trade Logs
```bash
# View in Excel/Numbers
cd logs
start trade_history.csv  # Windows
open trade_history.csv   # Mac

# View in terminal
cat logs/trade_history.csv
```

## ⚙️ Configuration

Edit `main.py` to customize:
```python
ACCOUNT_SIZE = 1_000_000   # ¥1,000,000 JPY
RISK_PER_TRADE = 0.02      # 2% per trade
MAX_DAILY_LOSS = 0.05      # 5% max daily loss
SCAN_INTERVAL = 60         # Seconds between scans
RUN_ONCE = False           # True for testing, False for production

TIMEFRAMES = {
    'trend': {
        'interval': '1h',
        'period': '1mo',
        'ma_periods': [50, 200]
    },
    'entry': {
        'interval': '1m',
        'period': '5d',
        'ma_periods': [20, 50]
    }
}
```

## 🔧 Development Workflow
```bash
# Daily workflow
cd gold-trading-bot
git pull

# Make changes...

git add .
git commit -m "Descriptive message"
git push
```

## 📚 Technical Details

### Indicators Used

**RSI (Relative Strength Index)**
- Period: 14
- Overbought: >70
- Oversold: <30
- Uses Wilder's smoothing method

**MACD (Moving Average Convergence Divergence)**
- Fast: 12-period EMA
- Slow: 26-period EMA
- Signal: 9-period EMA
- Histogram shows momentum strength

**Bollinger Bands**
- Period: 20
- Standard Deviation: 2.0
- Detects volatility squeezes
- Shows overbought/oversold extremes

**Moving Averages**
- Fast: 50-period SMA
- Slow: 200-period SMA
- Golden Cross: Fast crosses above Slow (bullish)
- Death Cross: Fast crosses below Slow (bearish)

## ⚠️ Important Notes

### Risk Warning
- This is for **educational purposes only**
- Always test strategies thoroughly
- Past performance ≠ future results
- Only trade with money you can afford to lose
- Currently in paper trading mode (no real money)

### Security
- Never commit `.env` to Git
- Keep API keys private
- Use environment variables for secrets

## 🎯 Development Roadmap

### ✅ Phase 1: Foundation (COMPLETE)
- [x] Data fetcher with hybrid approach
- [x] All technical indicators (RSI, MACD, BB, MA)
- [x] Risk management system
- [x] Multi-timeframe strategy
- [x] Anti-repainting protection
- [x] Execution loop & logging

### 🔄 Phase 2: Paper Trading (NEXT)
- [ ] SQLite database setup
- [ ] Virtual portfolio system
- [ ] Position manager
- [ ] Order simulator
- [ ] Performance analytics
- [ ] Backtesting engine

### 📅 Phase 3: Advanced Features (FUTURE)
- [ ] Live trading mode (OANDA integration)
- [ ] Web dashboard
- [ ] Real-time notifications
- [ ] Multiple asset support
- [ ] Machine learning integration

## 🤝 Contributing

This is a personal learning project, but suggestions are welcome!

## 📞 Contact

- GitHub: [@ASHISHSHREEH](https://github.com/ASHISHSHREEH)
- Project: [gold-trading-bot](https://github.com/ASHISHSHREEH/gold-trading-bot)

## 📄 License

Educational purposes only. Not financial advice.

---

**Built with:** Python, pandas, yfinance, MetalPriceAPI, and a lot of coffee ☕