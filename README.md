# Gold Trading Bot — MT5 AI Edition

An automated trading bot for Gold (XAUUSD) and major indices.
Connects to MetaTrader5, analyses 5 timeframes, and places real trades on your FxPro demo account.
The bot also learns from every trade it takes to improve over time.

---

## What It Does

Every 5 minutes the bot:

1. Reads live prices from your MT5 terminal
2. Analyses 5 timeframes (H4 → H1 → M15 → M5 → M1) to find setups
3. Scores the signal — needs 3+ confluence factors to fire
4. Asks the AI layer to approve or reject the trade
5. Places a market order with automatic Stop Loss and Take Profit
6. Manages open trades: partial close at 1R profit, moves SL to breakeven, trails stop
7. Records every trade (wins and losses) into a SQLite database
8. Feeds outcomes back into the AI so it learns what works

---

## Current Status

| Part | Status |
|------|--------|
| MT5 connection (FxPro Demo) | ✅ Working |
| 5-timeframe signal engine | ✅ Working |
| Risk management (SL/TP/trail) | ✅ Working |
| News blackout filter | ✅ Working — ForexFactory live feed + recurring schedule |
| Trade close detection | ✅ Fixed — profit and exit price now record correctly |
| AI learning layer | ✅ Working (needs 50+ trades for ML, 30+ for RL) |
| Phase 3 strict mode | ✅ Active from trade 0 — score ≥ 3 required |
| Counter-trend trades | ✅ Enabled — H4 conflict loses bonus but doesn't block |
| Gold min lot override | ✅ Uses 0.01 minimum when account too small to size properly |

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
ACCOUNT_FX_RATE=150.0
TELEGRAM_BOT_TOKEN=        ← optional, for alerts
TELEGRAM_CHAT_ID=          ← optional
NEWS_BLACKOUT=             ← optional, e.g. "FOMC 2026-06-11 19:00"
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

**To run a backtest on historical data:**
```bash
# First run — pulls data from MT5 and saves CSV
python backtest/run_backtest.py --save --symbol GOLD --currency JPY --fx-rate 150 --balance 50483

# Subsequent runs — use saved CSV (faster, no MT5 needed)
python backtest/run_backtest.py --csv --symbol GOLD --currency JPY --fx-rate 150 --balance 50483
```

---

## Trading Phases (Auto Mode)

The bot uses **Phase 3 strict mode from the very first trade**. Both transitional thresholds are set to 0 so it goes straight to strict.

| Trades | Phase | MIN_SCORE | Volume | H4 gate | Sessions |
|--------|-------|-----------|--------|---------|----------|
| 0+ | Phase 3: Strict | 3 | disabled* | off | Tokyo/London/NY |

\* Volume filter disabled for FxPro demo — tick data too sparse for meaningful comparison.

To re-enable the data collection ramp-up (phases 1→2→3), edit `config.py`:
```python
MODE_PHASE1_TRADES = 200   # restore gradual escalation
MODE_PHASE2_TRADES = 500
```

---

## How the Signal Works

The bot reads 5 timeframes from top to bottom. Each one scores +1 if it agrees.

```
H4  →  Big picture direction (bull or bear over days/weeks)
H1  →  Main trend gate — MUST be BULL or BEAR to open scoring
M15 →  Confirmation — must agree with H1 direction
M5  →  Entry zone — RSI pullback, BB position, ADX, Volume
M1  →  Timing — final momentum confirmation
```

### Score System (max 7 points, need ≥ 3 to fire)

| Factor | +1 if... |
|--------|----------|
| ADX | ADX ≥ 20 (trending market) |
| H4 confirms H1 | H4 and H1 same direction |
| M15 confirms | M15 MA or MACD agrees with H1 |
| RSI zone | BUY: RSI 40–55 (dip) / SELL: RSI 45–60 (rally) |
| BB position | BUY: near lower band / SELL: near upper band |
| M1 timing | M1 momentum agrees with signal direction |

### BUY vs SELL Logic

**BUY:** H1=BULL + M15 confirms + RSI in pullback zone (40–55) + BB near lower band

**SELL:** H1=BEAR + M15 confirms + RSI in rally zone (45–60) + BB near upper band

**Counter-trend trades** (H4 and H1 disagree): allowed but H4 bonus point not awarded. Needs 3 points from the remaining factors.

### H1 NEUTRAL = No Trade

If H1 is NEUTRAL (price stuck between MA50 and MA200), the scoring gate never opens and the bot stands aside regardless of other indicators.

```
price > MA50 > MA200  →  H1 = STRONG_BULL  ✅ BUY path opens
price > MA50          →  H1 = BULL         ✅ BUY path opens
price < MA50 < MA200  →  H1 = STRONG_BEAR  ✅ SELL path opens
price < MA50          →  H1 = BEAR         ✅ SELL path opens
price between MAs     →  H1 = NEUTRAL      ❌ no trade
```

---

## News Protection (2 Layers)

**Layer 1 — Calendar blackout:**
Blocks trading 30 min before and 30 min after high-impact events:
- Live feed from ForexFactory (refreshed hourly)
- Hardcoded recurring events: NFP, CPI, PPI, FOMC, Retail Sales, Jobless Claims, ISM, JOLTS
- Custom events via `NEWS_BLACKOUT` env variable

**Layer 2 — ATR spike guard:**
If current ATR > 2× the 20-bar average, the bot detects unexpected volatility and blocks entry even without a calendar event.

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

## Risk Settings

| Setting | Value | Meaning |
|---------|-------|---------|
| Risk per trade | 1% | Loses max 1% of balance per trade |
| Daily loss limit | 3% | Bot stops opening new trades if down 3% in a day |
| Max open trades | 4 | Never holds more than 4 positions at once |
| Min R:R ratio | 2.0 | Only takes trades with 2:1 reward-to-risk or better |
| Partial TP | 50% at 1R | Closes half the position when 1× risk in profit |
| Breakeven | At 1R | Moves SL to entry price after partial TP |
| Trailing stop | From 1.5R | Trails at 0.5× ATR once 1.5× risk in profit |

> ⚠️ **Gold lot size note:** With a ~50,000 JPY (~$320 USD) account, the risk-calculated lot for Gold is below the 0.01 minimum. The bot uses 0.01 lots (≈3–4% risk instead of 1%). This is acceptable for demo/learning but must be fixed before live trading. Account needs ~165,000 JPY (~$1,050 USD) for proper 1% risk sizing on Gold.

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
│   ├── moving_average.py    ← MA50 / MA200 trend classification
│   ├── atr.py               ← ATR (for stop sizing)
│   ├── adx.py               ← ADX regime filter
│   ├── news_filter.py       ← Calendar + ATR spike protection
│   └── swing_levels.py      ← Swing high/low for SL placement
│
├── trading/
│   ├── mt5_executor.py      ← Places and closes orders
│   ├── mt5_position_manager.py  ← Monitors positions, risk gates
│   └── trade_snapshot.py    ← Saves chart image on every trade
│
├── database/
│   └── trade_logger.py      ← Saves everything to SQLite (WAL mode)
│
├── learning/
│   ├── param_tuner.py       ← Tunes RSI/ATR/session settings
│   ├── signal_classifier.py ← RandomForest win-probability filter
│   ├── rl_agent.py          ← Q-learning reinforcement agent
│   ├── learning_engine.py   ← Combines all 3 AI components
│   └── learned_params.json  ← AI-updated settings (auto-generated)
│
├── backtest/
│   ├── backtest_engine.py   ← Test strategy on historical MT5 data
│   ├── run_backtest.py      ← Entry point for backtest runs
│   └── data_loader.py       ← Load from MT5 or saved CSV
│
├── snapshots/               ← Chart images saved on every trade
├── logs/                    ← Bot log files
├── data/trading_mt5.db      ← SQLite trade database (auto-created)
└── archive/                 ← Old pre-MT5 code (not used)
```

**Backup files (do not delete):**
```
main_mt5.py.adx_hard_gate_backup   ← version with ADX as hard block
config.py.adx_hard_gate_backup     ← matching config for above
```

---

## Development History

| Version | What was built |
|---------|---------------|
| v1.0 | Basic signal bot using yfinance, paper trading only |
| v1.1 | Added database, position manager, multi-timeframe |
| v2.0 | Full MT5 rewrite — live execution, 5 timeframes, ATR stops |
| v2.1 | AI learning layer — param tuner, ML classifier, RL agent |
| v2.2 | Auto-phase escalation, trade snapshot images, archive cleanup |
| v2.3 | 7 institutional upgrades: ADX filter, news filter, swing SL, ForexFactory feed, zombie cleanup, JPY FX rate, pre-flight order check |
| v2.4 | Bug fixes: trade close detection (profit=0 fixed), ghost events, missing entry_spread, end_session crash |
| v2.5 | ADX → score point (not hard block), counter-trend trades enabled, Gold min lot override |

---

## Account

- **Broker**: FxPro Demo
- **Account**: 591053144
- **Currency**: JPY
- **Leverage**: 1:200
- **Symbols**: GOLD, #USSPX500, #US100_M26, #Japan225
