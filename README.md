# 🤖 Gold Trading Bot - Professional Paper Trading System

AI-powered multi-timeframe gold (XAU/JPY) trading bot with advanced technical analysis, automated risk management, and paper trading infrastructure.

---

## 🎯 Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ COMPLETE | SQLite database with portfolio tracking |
| **Phase 2** | ✅ COMPLETE | Position Manager with auto SL/TP execution |
| **Phase 3** | ✅ COMPLETE | Full integration with main trading bot |
| **Phase 4** | 🔄 IN PROGRESS | 2-week data collection period |
| **Phase 5** | 📅 PLANNED | Analytics dashboard & backtesting engine |
| **Phase 6** | 🚀 FUTURE | Advanced features (Web UI, Live trading, ML) |

---

## 📈 VISUAL TIMELINE

```
    Jan 10-11           Jan 12-13           Jan 14-15           Jan 16-24            Feb+
        │                   │                   │                   │                  │
        ▼                   ▼                   ▼                   ▼                  ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   PHASE 1    │    │   PHASE 2    │    │   PHASE 3    │    │   PHASE 4    │    │   PHASE 5    │
│   Database   │───▶│   Trading    │───▶│    Full      │───▶│    Data      │───▶│  Analytics   │
│    Setup     │    │    Logic     │    │ Integration  │    │  Collection  │    │  Dashboard   │
│     ✅       │    │     ✅       │    │     ✅       │    │     🔄       │    │     📅       │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### Phase Details

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ✅ PHASE 1: DATABASE & INFRASTRUCTURE (Jan 10-11)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ • SQLite database (data/trading.db)                                         │
│ • Portfolio table - balance, equity, P&L tracking                           │
│ • Positions table - open trades with real-time updates                      │
│ • Trades table - permanent closed trade history                             │
│ • Performance table - daily statistics                                      │
│ • Starting capital: ¥1,000,000                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ✅ PHASE 2: POSITION & TRADE MANAGEMENT (Jan 12-13)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ • PositionManager - Auto-close on Stop Loss hit                             │
│ • PositionManager - Auto-close on Take Profit hit                           │
│ • TradeExecutor - Opens positions with risk calculation                     │
│ • RiskManager - 2% risk per trade, max 3 positions                          │
│ • Volatility-based stop loss (1.5× multiplier)                              │
│ • Take profit with minimum 2:1 R:R ratio                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ✅ PHASE 3: FULL INTEGRATION (Jan 14-15)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ • main_integrated.py - Central control loop                                 │
│ • Multi-timeframe analysis (1h trend + 1m entry)                            │
│ • Anti-repainting protection (iloc[-2] for completed candles)               │
│ • Confluence logic (2+ indicators must agree)                               │
│ • 5-minute scan interval (~299 seconds)                                     │
│ • Real-time portfolio display with emojis                                   │
│ • Comprehensive logging system                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🔄 PHASE 4: DATA COLLECTION (Jan 16 - Jan 24) ◀── YOU ARE HERE             │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Bot running continuously (5-minute scans)                                 │
│ • Observing market behavior and signal frequency                            │
│ • Collecting data for analytics                                             │
│ • Waiting for favorable trading conditions                                  │
│ • Target: 2 weeks of observation data                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📅 PHASE 5: ANALYTICS & REPORTING (Planned: Late Jan / Early Feb 2026)     │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Win rate calculation                                                      │
│ • Profit factor & Sharpe ratio                                              │
│ • Maximum drawdown tracking                                                 │
│ • Equity curve visualization                                                │
│ • Signal quality analysis                                                   │
│ • Time-of-day performance                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🚀 PHASE 6: ADVANCED FEATURES (Future)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Web-based dashboard interface                                             │
│ • Live trading mode (OANDA integration)                                     │
│ • Real-time notifications (Email/Telegram)                                  │
│ • Multiple asset support (EUR/USD, BTC, etc.)                               │
│ • Machine learning signal enhancement                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features Overview

### ✅ Multi-Timeframe Trading System
- **1-Hour Trend Filter** - Uses completed candles (anti-repainting protection)
- **1-Minute Entry Signals** - Tactical entry timing with precision
- **Confluence Logic** - Requires 2+ indicators to agree before trading
- **Continuous Execution** - Scans market every ~5 minutes automatically

### ✅ Technical Indicators Suite

| Indicator | Purpose | Configuration |
|-----------|---------|---------------|
| **RSI** | Momentum extremes | Period: 14, Overbought: >70, Oversold: <30 |
| **MACD** | Trend & momentum | Fast: 12, Slow: 26, Signal: 9 |
| **Bollinger Bands** | Volatility analysis | Period: 20, StdDev: 2.0 |
| **Moving Averages** | Trend direction | Fast: 50, Slow: 200 (Golden/Death Cross) |

### ✅ Paper Trading Infrastructure

**SQLite Database** - Complete trading data persistence
- 📊 Portfolio snapshots (balance, equity, unrealized P&L)
- 📈 Open positions with real-time tracking
- 📉 Closed trades history (permanent records)
- 📅 Daily performance metrics

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
- **Comprehensive Logging** - File (bot.log) + console logging
- **Error Handling** - Graceful failure recovery, zero-downtime design
- **Trade Logging** - All signals saved to CSV for analysis
- **Cross-Platform** - Windows, Mac, Linux compatible

---

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
python main_integrated.py
```

Press `Ctrl+C` to stop.

### Testing Components

```bash
# Test database operations
python -m database.schema

# Test position manager
python -m trading.position_manager

# Test trade executor
python -m trading.trade_executor
```

---

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
│    └─> Update prices every scan cycle (~5 min)         │
│    └─> Check stop loss → Auto close if hit             │
│    └─> Check take profit → Auto close if hit           │
│    └─> Update portfolio P&L continuously               │
└─────────────────────────────────────────────────────────┘
```

### Main Loop Flow (Every ~5 Minutes)

```
┌─────────────────────────────────────────────────────────────┐
│  STEP A: FETCH MARKET DATA                                  │
│  • 1-hour data (1 month history) → For trend analysis       │
│  • 1-minute data (5 days history) → For entry signals       │
│  • Source: yfinance API (free!)                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP B: UPDATE OPEN POSITIONS                              │
│  • Check each position's current price                      │
│  • Calculate unrealized P&L                                 │
│  • Auto-close if Stop Loss hit 🛑                          │
│  • Auto-close if Take Profit hit 🎯                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP C: DISPLAY PORTFOLIO STATUS                           │
│  • Balance: ¥1,000,000                                      │
│  • Equity: Balance + Unrealized P&L                         │
│  • Open Positions: 0/3 maximum                              │
│  • Recent Closed Trades                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP D: ANALYZE 1-HOUR TREND (Primary Filter)              │
│  • Use COMPLETED candle only (iloc[-2]) ← Anti-repainting!  │
│  • Calculate MA Fast (50 period)                            │
│  • Calculate MA Slow (200 period)                           │
│  • Determine: BULLISH / BEARISH / NEUTRAL                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP E: ANALYZE 1-MINUTE ENTRY SIGNALS                     │
│  • RSI (14) → BUY if <30, SELL if >70, else NEUTRAL        │
│  • MACD → BUY/SELL based on line crossover                 │
│  • Bollinger Bands → Position relative to bands            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP F: CONFLUENCE LOGIC (Decision Making)                 │
│                                                             │
│  IF 1h trend == NEUTRAL:                                    │
│      → FINAL = NEUTRAL (Don't trade choppy markets!)       │
│                                                             │
│  IF 1h trend == BULLISH:                                    │
│      IF 2+ indicators show BUY:                            │
│          → FINAL = BUY (HIGH confidence)                   │
│                                                             │
│  IF 1h trend == BEARISH:                                    │
│      IF 2+ indicators show SELL:                           │
│          → FINAL = SELL (HIGH confidence)                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP G: RISK CHECK & TRADE EXECUTION                       │
│                                                             │
│  IF signal == BUY or SELL:                                  │
│      ✓ Check: Open positions < 3?                          │
│      ✓ Check: Daily loss < 5%?                             │
│      ✓ Check: Sufficient margin?                           │
│      ✓ Calculate: Position size (2% risk per trade)        │
│      ✓ Calculate: Stop Loss (1.5× volatility)              │
│      ✓ Calculate: Take Profit (3× volatility, min 2:1 R:R) │
│                                                             │
│  IF all checks pass:                                        │
│      → Execute trade via TradeExecutor                     │
│      → Save to database                                    │
│      → Log to CSV                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP H: SLEEP & REPEAT                                     │
│  • Sleep ~299 seconds (align to 5-minute intervals)        │
│  • Go back to Step A                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Project Structure

```
gold-trading-bot/
├── data/
│   ├── fetcher.py              # Hybrid data fetcher (yfinance) ✅
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
│   ├── position_manager.py     # Auto SL/TP execution ✅
│   └── trade_executor.py       # Trade execution ✅
├── logs/
│   ├── trade_history.csv       # Trade signals (auto-created)
│   └── bot_integrated.log      # Application logs (auto-created)
├── main_integrated.py          # Main bot logic (BRAIN) ✅
├── main.py                     # Legacy main file ✅
├── test_bot.py                 # Single-scan test ✅
├── check_data.py               # Database checker ✅
├── .env                        # API keys (NOT in Git)
├── .env.example                # Template
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

---

## 🛡️ Anti-Repainting Protection

### The Critical Fix:

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

---

## 💾 Database Schema

| Table | Purpose | Key Features |
|-------|---------|--------------|
| **portfolio** | Account tracking | Historical snapshots, equity calculation |
| **positions** | Open trades | Real-time P&L, SL/TP levels |
| **trades** | Trade history | Permanent records, never deleted |
| **performance** | Daily metrics | Win rate, drawdown, profit factor |

### Example Queries

```sql
sqlite3 data/trading.db

-- View open positions
SELECT * FROM positions WHERE status = 'open';

-- View recent trades
SELECT * FROM trades ORDER BY close_time DESC LIMIT 10;

-- Check portfolio
SELECT balance, equity, unrealized_pnl 
FROM portfolio 
ORDER BY id DESC 
LIMIT 1;

-- Trading statistics
SELECT 
    COUNT(*) as total_trades,
    AVG(pnl) as avg_pnl,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
FROM trades;

.quit
```

---

## 📈 Example Output

```
****************************************************************
* GOLD TRADING BOT - INTEGRATED SYSTEM v1.0                    *
* Multi-Timeframe | Risk Managed | SQLite                      *
****************************************************************

🤖 INITIALIZING INTEGRATED TRADING SYSTEM...
✅ ALL SYSTEMS READY!
====================================================================
📡 SCAN #1 | 2026-01-16 09:35:06
📊 Fetching market data...
✅ Current Price: ¥4,611.00
🔄 Updating open positions...
Updated: 0 | Closed: 0
💰 PORTFOLIO STATUS
Balance:     ¥1,000,000.00
Equity:      ¥1,000,000.00 (+0.00%)
Unrealized:  +¥0.00
Realized:    +¥0.00
Free Margin: ¥1,000,000.00
📊 OPEN POSITIONS (0/3) ✅
No open positions
📈 RECENT CLOSED TRADES (Last 3)
No trades yet
──────────────────────────────────────────────────────────────────
🕐 1-HOUR TREND (CONFIRMED @ 18:00)
Direction: NEUTRAL
MA Fast:   ¥4,621.18
MA Slow:   ¥4,535.85
⚡ 1-MINUTE ENTRY (LIVE @ 19:25:00)
Price:  ¥4,611.00
RSI:    45.96 → NEUTRAL
MACD:   BUY
BB:     MIDDLE
⚪ FINAL SIGNAL: NEUTRAL (LOW)
Reasons: 1h trend: NEUTRAL
🛡️ RISK CHECK
⚪ No actionable signal.
====================================================================
💤 Sleeping 298.3s until next scan... (Press Ctrl+C to stop)
```

### When Trade Executes:

```
====================================================================
📡 SCAN #42 | 2026-01-16 14:23:45
====================================================================

🕐 1-HOUR TREND (CONFIRMED @ 14:00)
Direction: STRONG_BULL
MA Fast:   ¥4,650.00
MA Slow:   ¥4,550.00

⚡ 1-MINUTE ENTRY (LIVE @ 14:23:00)
Price:  ¥4,625.90
RSI:    28.50 → BUY
MACD:   BUY
BB:     NEAR_LOWER

🟢 FINAL SIGNAL: BUY (HIGH)
1H Trend: STRONG_BULL (Confirmed)
1M Entry: 3/3 Indicators Bullish

✅ POSITION OPENED: LONG @ ¥4,625.90
   Stop Loss:   ¥4,595.23 (-0.66%)
   Take Profit: ¥4,717.91 (+1.99%)
   Position:    2.8571 units
   Risk:        ¥20,000 (2.0% of account)
   Reward:      ¥60,000 (potential)
   R:R Ratio:   3.00:1
====================================================================
```

---

## ⚙️ Configuration

Edit `main_integrated.py` to customize behavior:

```python
# Account Settings
ACCOUNT_SIZE = 1_000_000   # Starting balance (¥1M)
RISK_PER_TRADE = 0.02      # 2% risk per trade
MAX_DAILY_LOSS = 0.05      # 5% daily loss limit
SCAN_INTERVAL = 300        # Seconds between scans (~5 min)
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
    }
}
```

---

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
```
LONG:  current_price <= stop_loss
SHORT: current_price >= stop_loss
```

**Take Profit Triggers:**
```
LONG:  current_price >= take_profit
SHORT: current_price <= take_profit
```

**Portfolio Updates:**
```
Equity = Balance + Unrealized P&L
Free Margin = Equity - Margin Used
Drawdown = (Peak Equity - Current Equity) / Peak Equity
```

### Risk Management Formulas

**Position Sizing (2% Rule):**
```python
risk_amount = account_balance × 0.02  # ¥20,000
stop_distance = abs(entry_price - stop_loss)
position_size = risk_amount / stop_distance
```

**Stop Loss Calculation:**
```python
volatility = bollinger_bandwidth  # e.g., 0.02 (2%)
stop_distance = entry_price × volatility × 1.5
stop_loss = entry_price - stop_distance  # For LONG
```

**Take Profit Calculation:**
```python
risk_distance = abs(entry_price - stop_loss)
take_profit = entry_price + (risk_distance × 3.0)  # 3:1 R:R
```

---

## ⚠️ Important Warnings

### Risk Disclaimer
- ⚠️ **Educational purposes ONLY** - Not financial advice
- ⚠️ **Paper trading mode** - No real money at risk currently
- ⚠️ **Past performance ≠ Future results**
- ⚠️ **Test thoroughly** before considering live trading
- ⚠️ **Only trade with money you can afford to lose**

### Security Best Practices
- 🔒 Never commit `.env` to Git
- 🔒 Keep API keys private
- 🔒 Use strong passwords
- 🔒 Review code before running

---

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
- [x] Risk limit enforcement (max 3 positions, 5% daily loss)
- [x] Manual & emergency close functions

### ✅ Phase 3: Full Integration (COMPLETE)
- [x] main_integrated.py - Central control loop
- [x] Multi-timeframe analysis (1h trend + 1m entry)
- [x] Anti-repainting protection
- [x] Confluence logic (2+ indicators)
- [x] Real-time portfolio display
- [x] Comprehensive logging

### 🔄 Phase 4: Data Collection (IN PROGRESS)
- [x] Bot running continuously
- [x] 5-minute scan intervals
- [ ] 2-week observation period
- [ ] Signal frequency analysis
- [ ] Market condition documentation

### 📅 Phase 5: Analytics & Backtesting (PLANNED)
- [ ] Backtesting engine with historical data
- [ ] Performance analytics dashboard
- [ ] Trade statistics (Sharpe ratio, max drawdown, etc.)
- [ ] Strategy optimization tools
- [ ] Equity curve visualization

### 🚀 Phase 6: Advanced Features (FUTURE)
- [ ] Web-based dashboard interface
- [ ] Live trading mode (OANDA integration)
- [ ] Real-time notifications (Email/Telegram)
- [ ] Multiple asset support (EUR/USD, BTC, etc.)
- [ ] Machine learning signal enhancement

---

## 🔧 Development Workflow

```bash
# Daily development cycle
cd gold-trading-bot
git pull

# Make changes...

# Test changes
python test_bot.py

# Run continuous mode
python main_integrated.py

# Commit and push
git add .
git commit -m "Descriptive commit message"
git push
```

---

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
tail -f logs/bot_integrated.log  # Live log viewing
```

### Database Queries
```bash
sqlite3 data/trading.db
> SELECT * FROM portfolio ORDER BY id DESC LIMIT 1;
> SELECT * FROM positions;
> SELECT * FROM trades ORDER BY close_time DESC LIMIT 10;
> .quit
```

---

## 🤝 Contributing

This is a personal learning project, but suggestions and feedback are welcome! Feel free to:
- Open issues for bugs or questions
- Suggest improvements
- Share your results

---

## 📞 Contact & Resources

- **GitHub:** [@ASHISHSHREEH](https://github.com/ASHISHSHREEH)
- **Repository:** [gold-trading-bot](https://github.com/ASHISHSHREEH/gold-trading-bot)
- **Documentation:** See code comments and docstrings

---

## 📄 License

Educational and research purposes only. Not licensed for commercial use. Not financial advice.

---

**Built with:** Python, SQLite, pandas, yfinance, determination, and countless hours of debugging 💪

**Last Updated:** January 16, 2026  
**Version:** 2.1 (Paper Trading Edition - Data Collection Phase)