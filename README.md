# 🤖 Gold Trading Bot - Professional Paper Trading System

AI-powered multi-timeframe gold (XAU/JPY) trading bot with advanced technical analysis, automated risk management, and paper trading infrastructure.

## 🎯 Project Status

✅ **Phase 1 COMPLETE** - SQLite database with portfolio tracking  
✅ **Phase 2 COMPLETE** - Position Manager with auto SL/TP execution  
🚀 **Phase 3 NEXT** - Full integration with main trading bot

## ✨ Features Overview

### ✅ Multi-Timeframe Trading System
- **1-Hour Trend Filter** - Uses completed candles (anti-repainting protection)
- **1-Minute Entry Signals** - Tactical entry timing with precision
- **Confluence Logic** - Requires 2+ indicators to agree before trading
- **Continuous Execution** - Scans market every 60 seconds automatically

### ✅ Technical Indicators Suite
| Indicator | Purpose | Configuration |
|-----------|---------|---------------|
| **RSI** | Momentum extremes | Period: 14, Overbought: >70, Oversold: <30 |
| **MACD** | Trend & momentum | Fast: 12, Slow: 26, Signal: 9 |
| **Bollinger Bands** | Volatility analysis | Period: 20, StdDev: 2.0 |
| **Moving Averages** | Trend direction | Fast: 50, Slow: 200 (Golden/Death Cross) |

### ✅ Paper Trading Infrastructure

**SQLite Database** - Complete trading data persistence
- Portfolio snapshots (balance, equity, unrealized P&L)
- Open positions with real-time tracking
- Closed trades history (permanent records)
- Daily performance metrics

**Position Manager** - Automated trade execution
- ✅ Automatic stop loss execution
- ✅ Automatic take profit execution  
- ✅ Real-time portfolio updates
- ✅ Risk limit enforcement (max 3 positions, 5% daily loss)
- ✅ Manual & emergency close functions

### ✅ Risk Management System
- **Dynamic Position Sizing** - 2% account risk per trade
- **Volatility-Based Stops** - Adaptive to market conditions
- **R:R Validation** - Minimum 2:1 reward-to-risk ratio
- **Daily Loss Limits** - 5% maximum drawdown protection
- **Position Limits** - Maximum 3 concurrent trades
- **Drawdown Protection** - Automatically stops trading if limits breached

### ✅ Data Pipeline
- **yfinance** - Free historical OHLCV data (no API key required)
- **MetalPriceAPI** - Real-time spot gold prices (optional)
- **Hybrid Approach** - Optimal data quality from multiple sources

### ✅ Production Features
- **Anti-Repainting Protection** - Uses completed candles for trend analysis
- **Comprehensive Logging** - File (`bot.log`) + console logging
- **Error Handling** - Graceful failure recovery, zero-downtime design
- **Trade Logging** - All signals saved to CSV for analysis
- **Cross-Platform** - Windows, Mac, Linux compatible

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
# Optional: Create .env for MetalPriceAPI
cp .env.example .env
notepad .env  # Add: METALPRICE_API_KEY=your_key_here
```

### Running the Bot
```bash
# Test mode (single scan)
python test_bot.py

# Production mode (continuous scanning)
python main.py
```

Press `Ctrl+C` to stop.

### Testing Components
```bash
# Test database operations
python -m database.schema

# Test position manager
python -m trading.position_manager
```

## 📊 How It Works

### Multi-Timeframe Strategy Flow
```
┌─────────────────────────────────────────────────────────┐
│ 1. 1-HOUR TIMEFRAME (Trend Filter)                     │
│    └─> Uses COMPLETED candle (anti-repainting)         │
│    └─> Calculates 50 & 200 period MAs                  │
│    └─> Determines trend: STRONG_BULL/BULL/NEUTRAL      │
│    └─> Detects Golden/Death Cross signals              │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 2. 1-MINUTE TIMEFRAME (Entry Signal)                   │
│    └─> RSI: Oversold (<30) or Overbought (>70)        │
│    └─> MACD: Bullish or Bearish momentum              │
│    └─> Bollinger Bands: Price at extremes             │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 3. CONFLUENCE LOGIC                                     │
│    ✅ BUY:  1h bullish + 2+ bullish 1m signals         │
│    ✅ SELL: 1h bearish + 2+ bearish 1m signals         │
│    ⚪ NEUTRAL: Conflicting signals → WAIT              │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 4. RISK MANAGEMENT                                      │
│    └─> Calculate position size (2% risk)               │
│    └─> Set stop loss (volatility-based)                │
│    └─> Set take profit (minimum 2:1 R:R)               │
│    └─> Validate trade meets all requirements           │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 5. POSITION MONITORING (Paper Trading)                 │
│    └─> Update prices every scan cycle                  │
│    └─> Check stop loss → Auto close if hit             │
│    └─> Check take profit → Auto close if hit           │
│    └─> Update portfolio P&L continuously               │
└─────────────────────────────────────────────────────────┘
```

## 🏗️ Project Structure
```
gold-trading-bot/
├── data/
│   ├── fetcher.py              # Hybrid data fetcher ✅
│   └── trading.db              # SQLite database (auto-created) ✅
├── database/
│   └── schema.py               # Database schema & operations ✅
├── indicators/
│   ├── rsi.py                  # RSI calculator ✅
│   ├── macd.py                 # MACD calculator ✅
│   ├── bollinger.py            # Bollinger Bands calculator ✅
│   └── moving_average.py       # MA with Golden/Death Cross ✅
├── trading/
│   ├── risk_manager.py         # Risk management system ✅
│   ├── trade_logger.py         # CSV trade logging ✅
│   └── position_manager.py     # Auto SL/TP execution ✅
├── logs/
│   ├── trade_history.csv       # Trade signals (auto-created)
│   └── bot.log                 # Application logs (auto-created)
├── main.py                     # Main bot logic ✅
├── test_bot.py                 # Single-scan test ✅
├── .env                        # API keys (NOT in Git)
├── .env.example                # Template
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

## 🛡️ Anti-Repainting Protection

**The Critical Fix:**
```python
# ❌ WRONG (Repainting Bug):
current_price = df['close'].iloc[-1]  # Uses forming candle
# At 10:15 AM → Sees incomplete 10:00-11:00 candle
# Price spikes → Bot enters trade
# By 10:59 AM → Candle closes red (repaints!)
# Result: Trade based on false signal

# ✅ CORRECT (Anti-Repainting):
current_price = df['close'].iloc[-2]  # Uses completed candle
# At 10:15 AM → Sees completed 9:00-10:00 candle
# Result: No repainting possible, reliable signals
```

**Why This Matters:** Prevents false signals that would cause ~30-40% of losing trades in production systems.

## 💾 Database Schema

| Table | Purpose | Key Features |
|-------|---------|--------------|
| **portfolio** | Account tracking | Historical snapshots, equity calculation |
| **positions** | Open trades | Real-time P&L, SL/TP levels |
| **trades** | Trade history | Permanent records, never deleted |
| **performance** | Daily metrics | Win rate, drawdown, profit factor |

## 📈 Example Output
```
====================================================================
   📡 SCAN #1 | 2026-01-14 02:34:56
====================================================================

   🕐 1-HOUR TREND (CONFIRMED/CLOSED)
      Candle Time: 2026-01-14 10:00
      Price:       ¥4,602.40
      Trend:       STRONG_BULL
      MA Fast/Slow: ¥4,520.05 / ¥4,440.98

   ⚡ 1-MINUTE ENTRY (LIVE/FORMING)
      Time:  02:34:56
      Price: ¥4,625.90
      RSI:   28.50 → BUY
      MACD:  BUY (MODERATE)
      BB:    NEAR_LOWER

   🟢 FINAL SIGNAL: BUY (HIGH)
      1H Trend: STRONG_BULL (Confirmed)
      1M Entry: 3/3 Indicators Bullish
====================================================================

✅ POSITION OPENED: LONG @ 4625.90
   Stop Loss:   ¥4,595.23 (-0.66%)
   Take Profit: ¥4,717.91 (+1.99%)
   Position:    2.8571 units
   Risk:        ¥20,000 (2.0% of account)
   Reward:      ¥60,000 (potential)
   R:R Ratio:   3.00:1

💤 Sleeping 58.2s until next scan...
```

## 🧪 Testing

### Component Tests
```bash
# Test database (portfolio, positions, trades)
python -m database.schema

# Test position manager (SL/TP execution)
python -m trading.position_manager

# Test single bot scan
python test_bot.py
```

### Continuous Mode
```bash
# Run continuously (production mode)
python main.py

# Stop with Ctrl+C to see session summary
```

## 📊 Viewing Results

### Trade History
```bash
cd logs
start trade_history.csv  # Windows
open trade_history.csv   # Mac
cat trade_history.csv    # Linux
```

### Application Logs
```bash
tail -f logs/bot.log     # Live log viewing
```

### Database Queries
```bash
sqlite3 data/trading.db

# View open positions
> SELECT * FROM positions;

# View recent trades
> SELECT * FROM trades ORDER BY close_time DESC LIMIT 10;

# Check portfolio
> SELECT balance, equity, unrealized_pnl FROM portfolio ORDER BY id DESC LIMIT 1;

> .quit
```

## ⚙️ Configuration

Edit `main.py` to customize behavior:
```python
# Account Settings
ACCOUNT_SIZE = 1_000_000   # Starting balance (¥1M)
RISK_PER_TRADE = 0.02      # 2% risk per trade
MAX_DAILY_LOSS = 0.05      # 5% daily loss limit
SCAN_INTERVAL = 60         # Seconds between scans
RUN_ONCE = False           # True for testing

# Timeframe Settings
TIMEFRAMES = {
    'trend': {
        'interval': '1h',        # Hourly candles
        'period': '1mo',         # 1 month history
        'ma_periods': [50, 200]  # Fast & slow MAs
    },
    'entry': {
        'interval': '1m',        # Minute candles
        'period': '5d',          # 5 days history
        'ma_periods': [20, 50]   # Fast & slow MAs
    }
}
```

## 📚 Technical Deep Dive

### Indicator Calculations

**RSI (Relative Strength Index)**
```
RSI = 100 - (100 / (1 + RS))
RS = Average Gain / Average Loss
Period: 14, Smoothing: Wilder's method
```

**MACD (Moving Average Convergence Divergence)**
```
MACD Line = 12 EMA - 26 EMA
Signal Line = 9 EMA of MACD
Histogram = MACD - Signal
```

**Bollinger Bands**
```
Middle Band = 20-period SMA
Upper Band = Middle + (2 × StdDev)
Lower Band = Middle - (2 × StdDev)
```

**Moving Averages**
```
SMA = Sum of last N prices / N
Golden Cross: 50 MA crosses above 200 MA (Bullish)
Death Cross: 50 MA crosses below 200 MA (Bearish)
```

### Position Manager Logic

**Stop Loss Triggers:**
- LONG: `current_price <= stop_loss`
- SHORT: `current_price >= stop_loss`

**Take Profit Triggers:**
- LONG: `current_price >= take_profit`
- SHORT: `current_price <= take_profit`

**Portfolio Updates:**
```python
Equity = Balance + Unrealized P&L
Free Margin = Equity - Margin Used
Drawdown = (Peak Equity - Current Equity) / Peak Equity
```

## ⚠️ Important Warnings

### Risk Disclaimer
- ⚠️ **Educational purposes ONLY** - Not financial advice
- ⚠️ **Paper trading mode** - No real money at risk currently
- ⚠️ **Past performance ≠ Future results**
- ⚠️ **Test thoroughly** before considering live trading
- ⚠️ **Only trade** with money you can afford to lose

### Security Best Practices
- 🔒 Never commit `.env` to Git
- 🔒 Keep API keys private
- 🔒 Use strong passwords
- 🔒 Review code before running

## 🎯 Development Roadmap

### ✅ Phase 1: Database Infrastructure (COMPLETE)
- [x] SQLite database with 4 tables
- [x] Portfolio tracking with historical snapshots
- [x] Position management system
- [x] Trade history with permanent records
- [x] Performance metrics calculation

### ✅ Phase 2: Position Manager (COMPLETE)
- [x] Real-time position monitoring
- [x] Automatic stop loss execution
- [x] Automatic take profit execution
- [x] Portfolio P&L updates
- [x] Risk limit enforcement
- [x] Manual & emergency close functions

### 🔄 Phase 3: Integration (IN PROGRESS)
- [ ] Integrate Position Manager with main bot
- [ ] Auto-open positions from trading signals
- [ ] Real-time SL/TP monitoring during scans
- [ ] Portfolio dashboard/summary view

### 📅 Phase 4: Analytics & Backtesting (PLANNED)
- [ ] Backtesting engine with historical data
- [ ] Performance analytics dashboard
- [ ] Trade statistics (Sharpe ratio, max drawdown, etc.)
- [ ] Strategy optimization tools

### 🚀 Phase 5: Advanced Features (FUTURE)
- [ ] Web-based dashboard interface
- [ ] Live trading mode (OANDA integration)
- [ ] Real-time notifications (email/Telegram)
- [ ] Multiple asset support (EUR/USD, BTC, etc.)
- [ ] Machine learning signal enhancement

## 🔧 Development Workflow
```bash
# Daily development cycle
cd gold-trading-bot
git pull

# Make changes...

# Test changes
python test_bot.py

# Commit and push
git add .
git commit -m "Descriptive commit message"
git push
```

## 🤝 Contributing

This is a personal learning project, but suggestions and feedback are welcome! Feel free to:
- Open issues for bugs or questions
- Suggest improvements
- Share your results

## 📞 Contact & Resources

- **GitHub:** [@ASHISHSHREEH](https://github.com/ASHISHSHREEH)
- **Repository:** [gold-trading-bot](https://github.com/ASHISHSHREEH/gold-trading-bot)
- **Documentation:** See code comments and docstrings

## 📄 License

Educational and research purposes only. Not licensed for commercial use. Not financial advice.

---

**Built with:** Python, SQLite, pandas, yfinance, determination, and countless hours of debugging 💪

**Last Updated:** January 14, 2026  
**Version:** 2.0 (Paper Trading Edition)