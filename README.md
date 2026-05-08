# Gold Trading Bot — MT5 AI Edition

An automated trading bot for Gold (XAUUSD) and major indices.
Connects to MetaTrader5, analyses 5 timeframes, and places real trades on your FxPro demo account.
The bot also learns from every trade it takes to improve over time.

---

## What It Does

Every 60 seconds the bot:

1. Reads live prices from your MT5 terminal
2. Analyses 5 timeframes (H4 → H1 → M15 → M5 → M1) to find setups
3. Asks the AI layer to approve or reject the trade
4. Places a market order with automatic Stop Loss and Take Profit
5. Manages open trades: partial close at 1R profit, moves SL to breakeven, trails stop
6. Records every trade (wins and losses) into a database
7. Feeds outcomes back into the AI so it learns what works

---

## Current Status

| Part | Status |
|------|--------|
| MT5 connection (FxPro Demo) | Working |
| 5-timeframe signal engine | Working |
| Risk management (SL/TP/trail) | Working |
| Trade snapshot images | Working |
| AI learning layer | Working (needs 200+ trades to activate fully) |
| Data collection phase | **Active now** — bot trading to gather data |
| Strict mode (live-ready) | Auto-switches at 200 trades (transitional) and 500 trades (strict) |

---

## How to Run

**Step 1 — Open MT5**
Open FxPro MetaTrader5 and wait for live prices to appear.
Make sure it is NOT running as Administrator.

**Step 2 — Set up your `.env` file**
Copy `.env.example` to `.env` and fill in your details:
```
MT5_LOGIN=591053144
MT5_PASSWORD=your_password
MT5_SERVER=FxPro-Demo4
MT5_SYMBOLS=GOLD,#USSPX500,#US100_M26,#Japan225
ACCOUNT_FX_RATE=158.0
```

**Step 3 — Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 4 — Run the bot**
```bash
python main_mt5.py
```

**To check your account balance and trade history:**
```bash
python check_data.py
```

**To diagnose MT5 connection problems:**
```bash
python mt5_debug.py
```

---

## Trading Phases (Auto Mode)

The bot automatically tightens its rules as it collects more trade data:

| Trades collected | Phase | What changes |
|-----------------|-------|-------------|
| 0 – 199 | Phase 1: Data Collection | Fires on any signal, no session filter, volume off |
| 200 – 499 | Phase 2: Transitional | Requires 2+ confluence factors, volume 50% |
| 500+ | Phase 3: Strict | Requires 3+ factors, volume 80%, session filter on, H4 hard gate |

You do not need to change anything — it switches automatically.

---

## How the Signal Works

The bot reads 5 timeframes from top to bottom. Each one must agree before moving to the next.

```
H4  →  Big picture direction (are we in a bull or bear market?)
H1  →  Main trend (which way is the trend right now?)
M15 →  Confirmation (is the short-term momentum agreeing?)
M5  →  Entry zone (is RSI in pullback zone? Are BB bands in position?)
M1  →  Timing (is momentum just turning in our direction?)
```

Each factor that agrees adds +1 to the score. Higher score = higher confidence.

In Phase 1 (now): score of 1 is enough to trade.
In Phase 3 (after 500 trades): score of 3 required.

---

## How the AI Works

Three AI components run in the background and vote on every signal:

**1. Parameter Tuner**
Looks at all past trades and finds the RSI levels, ATR sizes, and session times where the bot actually makes money. Updates automatically every few sessions.

**2. ML Classifier (RandomForest)**
Learns which market conditions lead to winning trades. Needs 50+ trades to activate. Returns a win probability (0.0 to 1.0). If below 0.35, it vetoes the trade.

**3. RL Agent (Q-learning)**
Learns by trial and error which action (buy/sell/hold) works best in each market state. Needs 30+ trades to activate.

**Combined vote:**
```
Base signal  60%  +  ML classifier  25%  +  RL agent  15%  =  Final decision
```

---

## Trade Snapshots

Every time the bot opens a trade, it saves a chart image to the `snapshots/` folder.

```
snapshots/
  GOLD_BUY_20260508_141522.png
  GOLD_SELL_20260508_160301.png
```

Each image shows:
- M5 candlestick chart with Bollinger Bands
- RSI panel with zones highlighted
- MACD panel
- Entry point arrow, SL line, TP line
- All the reasons the signal fired (shown in the title)

Use these to study why the bot took each trade.

---

## Risk Settings

| Setting | Value | Meaning |
|---------|-------|---------|
| Risk per trade | 1% | Loses max 1% of balance per trade |
| Daily loss limit | 3% | Bot stops opening new trades if down 3% in a day |
| Max open trades | 4 | Never holds more than 4 positions at once |
| Partial TP | 50% at 1R | Closes half the position when 1× risk in profit |
| Breakeven | At 1R | Moves SL to entry price after partial TP |
| Trailing stop | From 1.5R | Trails at 0.5× ATR once 1.5× risk in profit |

---

## File Structure

```
gold-trading-bot/
│
├── main_mt5.py              ← Run this to start the bot
├── check_data.py            ← Check account balance and trade history
├── mt5_debug.py             ← Diagnose MT5 connection problems
├── config.py                ← All settings (edit here, not in code)
├── requirements.txt         ← pip install -r requirements.txt
├── .env                     ← Your MT5 credentials (never commit this)
│
├── data/
│   └── mt5_fetcher.py       ← Gets live prices from MT5
│
├── indicators/
│   ├── rsi.py               ← RSI calculation
│   ├── macd.py              ← MACD calculation
│   ├── bollinger.py         ← Bollinger Bands
│   ├── moving_average.py    ← MA50 / MA200
│   └── atr.py               ← ATR (for stop sizing)
│
├── trading/
│   ├── mt5_executor.py      ← Places and closes orders
│   ├── mt5_position_manager.py  ← Monitors positions, risk gates
│   └── trade_snapshot.py    ← Saves chart image on every trade
│
├── database/
│   └── trade_logger.py      ← Saves everything to SQLite
│
├── learning/
│   ├── param_tuner.py       ← Tunes RSI/ATR/session settings
│   ├── signal_classifier.py ← RandomForest win-probability filter
│   ├── rl_agent.py          ← Q-learning reinforcement agent
│   ├── learning_engine.py   ← Combines all 3 AI components
│   └── learned_params.json  ← AI-updated settings (auto-generated)
│
├── backtest/
│   └── backtest_engine.py   ← Test the strategy on historical data
│
├── snapshots/               ← Chart images saved on every trade
├── logs/                    ← Bot log files
└── archive/                 ← Old pre-MT5 code (not used)
```

---

## Development History

| Phase | What was built |
|-------|---------------|
| v1.0 | Basic signal bot using yfinance, paper trading only |
| v1.1 | Added database, position manager, multi-timeframe |
| v2.0 | Full MT5 rewrite — live execution, 5 timeframes, ATR stops |
| v2.1 | AI learning layer — param tuner, ML classifier, RL agent |
| v2.2 | Auto-phase escalation, trade snapshot images, archive cleanup |

---

## Account

- **Broker**: FxPro Demo
- **Account**: 591053144
- **Currency**: JPY
- **Leverage**: 1:200
- **Symbols**: GOLD, #USSPX500, #US100_M26, #Japan225
