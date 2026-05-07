# Gold Trading Bot — MT5 AI Edition

**Production-grade algorithmic trading system for Gold (XAUUSD) and major indices.**
Built on MetaTrader5 with a five-timeframe signal engine, institutional risk management,
and a self-learning AI layer that improves with every trade.

---

## Project Status

| Component | Status | Description |
|-----------|--------|-------------|
| MT5 Integration | COMPLETE | Live execution via MetaTrader5 Python API |
| Five-Timeframe Engine | COMPLETE | H4 → H1 → M15 → M5 → M1 signal cascade |
| Risk Management | COMPLETE | ATR stops, partial TP, trailing, circuit-breakers |
| Backtest Engine | COMPLETE | Exact replication of live strategy on historical data |
| AI Parameter Tuner | COMPLETE | Statistical RSI/ATR/session optimisation |
| AI ML Classifier | COMPLETE | RandomForest win-probability filter |
| AI RL Agent | COMPLETE | Q-learning adaptive direction voter |
| Data Collection | ACTIVE | FxPro Demo4, relaxed filters to accumulate trade history |
| Live Deployment | PLANNED | After 200+ demo trades validate edge |

---

## What This Bot Does

Every 60 seconds the bot:

1. Reads live price data from your MT5 terminal across five timeframes
2. Runs a multi-timeframe confluence analysis to find high-probability setups
3. Asks the AI layer to vote on whether to take the trade
4. If approved, places a market order with ATR-based stops sized to 1% account risk
5. Manages open positions automatically: partial close at 1R, breakeven, trailing stop
6. Records every decision (including rejected signals) to SQLite for future learning
7. After the position closes, feeds the outcome back into the AI to improve future votes

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         main_mt5.py                                  │
│              Main scan loop · Session filter · Display               │
└────────────┬────────────────────────────┬────────────────────────────┘
             │                            │
    ┌────────▼────────┐        ┌──────────▼──────────┐
    │  Signal Engine  │        │   Position Manager   │
    │  (5 timeframes) │        │  Partial TP · Trail  │
    └────────┬────────┘        └──────────┬───────────┘
             │                            │
    ┌────────▼────────────────────────────▼───────────┐
    │                  AI Learning Layer               │
    │  ┌─────────────┐ ┌──────────────┐ ┌──────────┐  │
    │  │ ParamTuner  │ │  ML Classif. │ │ RL Agent │  │
    │  │ RSI/ATR/Vol │ │ RandomForest │ │Q-learning│  │
    │  └──────┬──────┘ └──────┬───────┘ └────┬─────┘  │
    │         └───────────────▼───────────────┘        │
    │              LearningEngine (orchestrator)        │
    └──────────────────────┬──────────────────────────-┘
                           │
    ┌──────────────────────▼──────────────────────────┐
    │              SQLite Database                     │
    │  trades · signals · sessions · learning_features │
    └──────────────────────┬──────────────────────────┘
                           │
    ┌──────────────────────▼──────────────────────────┐
    │           MetaTrader5 Terminal                   │
    │     Live prices · Order execution · History      │
    └─────────────────────────────────────────────────┘
```

---

## Complete File Structure

```
gold-trading-bot/
│
├── main_mt5.py                  ← Entry point — run this
├── config.py                    ← All tunables + .env loader
├── requirements.txt             ← pip dependencies
├── .env.example                 ← Template for MT5 credentials
│
├── data/
│   └── mt5_fetcher.py           ← MT5 OHLCV + tick + account data
│
├── indicators/
│   ├── atr.py                   ← Wilder's ATR (stop sizing)
│   ├── rsi.py                   ← RSI oscillator
│   ├── macd.py                  ← MACD histogram + signal
│   ├── bollinger.py             ← Bollinger Bands position
│   └── moving_average.py        ← SMA crossover analysis
│
├── trading/
│   ├── mt5_executor.py          ← Order placement, retry logic, lot sizing
│   └── mt5_position_manager.py  ← Risk gates, position queries, deal history
│
├── database/
│   └── trade_logger.py          ← SQLite schema, trade/signal/feature logging
│
├── learning/
│   ├── __init__.py
│   ├── param_tuner.py           ← Statistical parameter optimiser
│   ├── signal_classifier.py     ← RandomForest win-probability classifier
│   ├── rl_agent.py              ← Q-learning RL agent
│   ├── learning_engine.py       ← Thread-safe orchestrator
│   ├── learned_params.json      ← Live AI-tuned parameters (auto-updated)
│   └── models/                  ← Persisted classifier models
│       └── classifier_v{N}.pkl
│
├── backtest/
│   ├── backtest_engine.py       ← Full strategy replication on historical data
│   ├── data_loader.py           ← Historical OHLCV loader
│   └── run_backtest.py          ← CLI runner
│
└── logs/
    └── mt5_bot.log              ← Structured logs
```

---

## Signal Engine — Five Timeframes

The strategy uses a top-down cascade — each timeframe must agree before the next runs.

```
H4  ─── Big-picture direction (MA50 / MA200 crossover)
        Hard gate: if H4 opposes H1, all trades blocked
        │
        ▼
H1  ─── Major trend direction (MA50 / MA200)
        STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
        │
        ▼
M15 ─── Trend confirmation (MA20 / MA50 + MACD direction)
        Must agree with H1  →  +1 score point
        │
        ▼
M5  ─── Entry signals
        RSI pullback zone  (bull: 40–55 | bear: 45–60)
        Bollinger Band position
        Volume gate: current bar ≥ 80% of 20-bar average  [hard gate]
        │
        ▼
M1  ─── Timing confirmation (MACD + RSI midline cross)
        Momentum must agree with direction  →  +1 score point
```

**Score system:**

| Score | Confidence | Action |
|-------|-----------|--------|
| 4–6 | HIGH | Execute if AI agrees |
| 2–3 | MODERATE | Execute if AI agrees |
| 0–1 | LOW | NEUTRAL — no trade |

Minimum score to trade is 2 (configurable via `min_score` in learned params).

---

## AI Learning Layer

All three AI components are **advisory only** — they suppress bad trades,
they never create trades from a NEUTRAL base signal.

### 1. Parameter Tuner

Reads closed trade history and finds the parameter values where the bot
actually makes money — RSI zones, score thresholds, ATR multiples,
session weights, volume filters.

**Trust blending prevents overfitting:**
```
30 trades  →   0% learned  (all defaults, too little data)
100 trades →  41% learned
200 trades → 100% learned  (full trust in statistics)
```

**Hard guard-rails — no parameter can ever leave these bounds:**
```
rsi_bull_min: 25–50    rsi_bull_max: 45–70
rsi_bear_min: 30–55    rsi_bear_max: 50–75
atr_sl_mult:  1.0–3.0  atr_tp_mult:  2.0–5.0
volume_ratio: 0.0–1.5  min_score:    1–5
```

Runs every 5 sessions or after 20 new closed trades. Writes atomic JSON.
Bot picks up improved parameters on next startup.

---

### 2. ML Signal Classifier

A RandomForest that predicts win probability for each signal
given the 12 features recorded at trade entry.

**Features:**
```
macd_signal    bb_position    htf_trend      h1_trend
m15_trend      m1_direction   rsi            atr
spread         volume_ratio   base_score     session_hour
```

**Regularisation (anti-overfit):**
- `max_depth = 6` — shallow trees
- `min_samples_leaf = 5` — each leaf needs real data
- `class_weight = balanced` — handles unequal win/loss counts
- Platt scaling for calibrated probabilities

**Lifecycle:**
- Silent (returns 0.5) until 50 closed trades
- Retrains every 50 new trades on a background thread
- PSI drift detection flags when market has changed
- Keeps last 3 model versions in `learning/models/`

**Veto threshold:** `win_probability < 0.35` when active → trade suppressed

---

### 3. RL Agent

Tabular Q-learning — no GPU, < 1 MB RAM, runs on a Raspberry Pi.

**State space (3 375 states):**
```
trend (5) × RSI (5) × volatility (3) × session (5) × prev_outcome (3) × regime (3)
```

**Reward shaping:**
```
WIN:   +rr_achieved (capped at 3.0)
LOSS:  -1.0
After 5 consecutive losses: -0.5 × (streak/5) drawdown penalty
Trend aligned with H1:      +0.2 bonus
Revenge trade (< 5 min):    -0.3 penalty
```

Exploration decays: ε = 0.30 → 0.05 over 500 trades.
Persists to `learning/q_table.pkl` after every session.

---

### 4. Learning Engine (Orchestrator)

**Weighted ensemble:**
```
Base rule score  60%  ← strategy always dominates
ML classifier    25%  ← probabilistic filter
RL agent         15%  ← adaptive vote
```

**Composite confidence (0–10):**
```
confidence = (0.60 × base_norm + 0.25 × ml_score + 0.15 × rl_align) × 10
```

**Veto rules:**
```
Hard ML veto:  ML active AND win_prob < 0.35     → NEUTRAL
Joint veto:    RL = HOLD AND ML active AND win_prob < 0.45  → NEUTRAL
```

**Output on every signal:**
```
AI  │ score=4.0  ml=0.71  rl=BUY  conf=7.4/10  → BUY
AI  │ score=3.0  ml=0.31  rl=HOLD conf=4.1/10  → NEUTRAL  [ML hard veto: win_prob=0.31]
```

---

## Risk Management

**Per-trade sizing:** 1% of account balance, volatility-scaled lot size

**Stop placement:**
```
Stop Loss   = entry ± 1.5 × ATR
Take Profit = entry ± 3.0 × ATR   (2:1 R:R minimum)
```
If broker's minimum stop distance is wider than the ATR-derived stop,
the stop is widened automatically to comply. Trade is blocked if
resulting R:R falls below 2.0.

**Partial TP + trailing:**
```
At 1R profit    → Close 50%,  move SL to entry (free trade)
At 1.5R profit  → Trail SL at current_price ∓ 0.5×ATR
                   Trail only advances, never retreats
```

**Circuit-breakers (all new entries blocked):**
```
Max open positions:  4 total
Daily drawdown:      3% from session-start balance
Margin level:        < 200%
Duplicate symbol:    already have a trade in this symbol
```

---

## Database Schema

Four tables in `data/trading_mt5.db`:

```sql
sessions          — per-run summary
trades            — every executed trade (open + close data)
signals           — every signal evaluation including NEUTRAL and BLOCKED
learning_features — ML training corpus: 13 features + outcome per trade
```

`learning_features` is populated at trade open and updated when it closes:

```
Direction + symbol + all trend states at entry
RSI, MACD, BB, ATR, spread, volume ratio
Base score, session hour
ML score + RL vote + AI confidence at decision time
Outcome: 1=WIN, 0=LOSS  (filled on close)
Realised R:R, hold duration in minutes
```

---

## Setup

**Requirements:** Windows with MT5 terminal installed, Python 3.11+

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`:

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=FxPro.MT5-Demo4
MT5_PATH=C:\Program Files\FxPro MT5 Terminal\terminal64.exe
ACCOUNT_TYPE=DEMO
MT5_SYMBOLS=GOLD,#USSPX500,#US100_M26,#Japan225
MT5_MAGIC=20240101
ACCOUNT_FX_RATE=158.0
```

**Run:**
```bash
python main_mt5.py
```

**Backtest:**
```bash
python backtest/run_backtest.py --symbol GOLD --days 90
python backtest/run_backtest.py --symbol GOLD --days 90 --jpy
```

---

## Configuration Reference

| Parameter | Default | Note |
|-----------|---------|------|
| `RISK_PER_TRADE` | 0.01 | 1% of balance per trade |
| `MAX_DAILY_LOSS` | 0.03 | 3% daily drawdown limit |
| `MAX_POSITIONS` | 4 | Max simultaneous positions |
| `MIN_RR_RATIO` | 2.0 | Min R:R to place any order |
| `ATR_SL_MULT` | 1.5 | SL = entry ± ATR × this |
| `ATR_TP_MULT` | 3.0 | TP = entry ± ATR × this |
| `RSI_BULL_MIN/MAX` | 40/55 | RSI zone for BUY pullbacks |
| `RSI_BEAR_MIN/MAX` | 45/60 | RSI zone for SELL rallies |
| `VOLUME_MIN_RATIO` | 0.8 | Min M5 volume vs 20-bar avg |
| `SCAN_INTERVAL` | 60 | Seconds between cycles |
| `BREAKEVEN_AT_R` | 1.0 | Move SL to entry at this R |
| `TRAIL_START_AT_R` | 1.5 | Start trailing at this R |
| `TRAIL_ATR_MULT` | 0.5 | Trail distance = ATR × this |
| `PARTIAL_TP_RATIO` | 0.5 | Close this fraction at 1R |

*RSI and ATR params are auto-tuned by the AI after 200+ trades.*

---

## Full Development History

### Foundation (Jan 10–11, 2026)
- Project scaffolding, MetalPriceAPI data fetcher
- RSI + MACD indicators
- SQLite portfolio database
- Basic paper trading loop

### Position Management (Jan 12–13, 2026)
- Auto stop-loss and take-profit
- Risk manager: 2% per trade, max 3 positions
- Anti-repainting protection (confirmed closed candles only)
- Volatility-based stop sizing

### Full Integration (Jan 14–15, 2026)
- Connected data → signal → execution → logging pipeline
- Position tracking with real-time P&L
- 2-week paper trade test run initiated

### MT5 Live Engine (Apr 30, 2026) — PR #1
Replaced yfinance/MetalPriceAPI with direct MetaTrader5 integration:

- `MT5DataFetcher` — thin wrapper for OHLCV, tick, account data from terminal
- `MT5Executor` — live order placement:
  - Risk-based lot sizing (not fixed lots)
  - Broker minimum stop distance compliance
  - Exponential back-off retry on requotes/connection errors
  - R:R gate: orders below 2.0 R:R are blocked
  - Pre-flight `order_check()` before every send
- `MT5PositionManager` — three-layer account risk circuit-breaker
- `ATRCalculator` — Wilder's ATR for all volatility-based stops
- `TradeLogger` — offline SQLite analytics (MT5 is source of truth for live state)

### Strategy Upgrade (May 2, 2026) — PR #2
Five-timeframe system replacing two-timeframe:

1. **H4 bias gate** — hard block against big-picture trend
2. **RSI pullback zones** — trade pullbacks (40–55/45–60) not extremes
3. **Session filter** — active trading windows, dead-zone position management
4. **Partial TP + trailing** — 50% at 1R, breakeven, 0.5×ATR trail from 1.5R
5. **Volume gate** — M5 bar ≥ 80% of 20-bar average
6. **JPY account** — live USD/JPY FX rate from MT5 for lot sizing
7. **Backtest engine** — exact live-strategy replication on historical data

### AI Learning Layer (May 7, 2026) — current branch
Self-learning system using own trade history:

**`learning/param_tuner.py`** (406 lines)
- Exponential recency weighting, trust blending, bootstrap CI
- Tunes: RSI zones, ATR multiples, score threshold, volume ratio, session weights
- Atomic JSON writes, hard guard-rails

**`learning/signal_classifier.py`** (372 lines)
- 12-feature RandomForest, Platt-calibrated probabilities
- max_depth=6, min_samples_leaf=5, balanced classes
- StratifiedKFold CV with ROC-AUC, PSI drift detection
- Model versioning, background retraining

**`learning/rl_agent.py`** (379 lines)
- Tabular Q-learning, 3 375 states, < 1 MB RAM
- Shaped rewards, epsilon decay, persistent Q-table

**`learning/learning_engine.py`** (455 lines)
- Weighted ensemble (60/25/15), two veto rules
- Background daemon retrain thread (never blocks scan)
- Thread-safe throughout

**`database/trade_logger.py`** — extended with `learning_features` table
**`trading/mt5_position_manager.py`** — `get_recently_closed_deals()` for AI feedback
**`main_mt5.py`** — AI init, ai_vote() hook, close detection, session end lifecycle

---

## Roadmap

### Phase 7 — Data Collection (now → ~200 trades)
- [ ] Run continuously on FxPro demo
- [ ] Verify AI logging is clean (check `learning_features` table)
- [ ] Confirm classifier activates after trade 50
- [ ] Monitor `drift_score()` for distribution shift
- [ ] Run backtest on 90 days of XAUUSD to validate edge exists

### Phase 8 — Optimisation
- [ ] Session-specific RSI zones (London vs NY behave differently)
- [ ] Per-symbol classifiers (GOLD vs S&P500 vs Nikkei)
- [ ] News event filter (suppress trades near high-impact events)
- [ ] Spread spike detection and dynamic threshold
- [ ] Market regime classifier (trending / ranging / volatile)
- [ ] Streamlit performance dashboard (equity curve, AI decision audit log)

### Phase 9 — Live Preparation
- [ ] Shadow mode: run demo and live in parallel for 30 days
- [ ] Slippage and commission model in backtest
- [ ] Kelly criterion position sizing (with cap at 2%)
- [ ] Multi-broker abstraction layer
- [ ] Automated alert system (Telegram / email on circuit-breaker trips)
- [ ] Final validation checklist before removing `assert_demo_mode()`:
  - 200+ demo trades accumulated
  - Profit factor > 1.3 over 60+ consecutive days
  - Max drawdown never hit 5% on demo
  - AI models retrained at least 3 times

### Research Backlog
- Transformer signal model on raw OHLCV sequences
- Multi-asset correlation filter (block GOLD BUY when DXY bullish)
- Order flow / DOM imbalance gate
- ONNX model export (deploy without scikit-learn)

---

## Safety Notes

1. **Demo only.** `assert_demo_mode()` in `config.py` hard-blocks live account trading.
   Do not remove this until all Phase 9 checks are complete.

2. **AI fails safe.** If sklearn is missing, a model file is corrupted, or any AI
   component raises an exception, the bot logs a warning and falls back to
   pure rule-based execution. It never crashes the scan loop.

3. **RL explores randomly early.** At ε=0.30 the RL agent votes randomly ~30%
   of the time. This is correct — it needs to explore before it can learn.
   Votes don't affect execution unless combined with an ML soft veto.

4. **Learned parameters apply at next startup.** Changing `learned_params.json`
   mid-session has no effect. The file is read only in `main()`.

5. **Never raise risk to recover losses.** The 3% daily drawdown circuit-breaker
   exists to protect capital. When it trips, let it trip.

---

## License

Personal use and research only. Not financial advice.
Past demo performance does not guarantee live results.
