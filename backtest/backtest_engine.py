"""
Gold Bot Backtest Engine
Replicates the exact three-timeframe strategy from main_mt5.py on historical data.

Fixes vs the lean-bot engine:
  1. Unified P&L — direction * price_diff * contract_size * lots for every exit
  2. Commission — deducted per trade leg, separately from spread
  3. Partial TP — 50 % closed at 1R, SL → breakeven, trail from 1.5R (bar-by-bar)
  4. Equity curve — one point per bar, no gaps
  5. Annualised Sharpe — scaled by sqrt(bars / trades) not raw mean/std
  6. Same-bar SL+TP conflict — conservative: SL wins unless we're past partial TP
  7. Trail update AFTER exit check — avoids same-bar paradox
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

import config
from indicators.atr            import ATRCalculator
from indicators.rsi            import RSICalculator
from indicators.macd           import MACDCalculator
from indicators.bollinger      import BollingerBandsCalculator
from indicators.moving_average import MovingAverageCalculator

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CONTRACT_SIZE      = 100    # XAUUSD: 100 oz per standard lot
SPREAD_COST        = 0.35   # USD added to BUY entry / subtracted from SELL entry
COMMISSION_PER_LOT = 7.0   # USD round-trip per lot (FxPro typical)
LOT_STEP           = 0.01
MIN_LOT            = 0.01
MAX_LOT            = 50.0
MAX_BARS_HELD      = 200    # force-close after this many M5 bars (~17 hours)

_MA_PERIODS_TREND = [50, 200]   # H1 — slow, reliable trend filter
_MA_PERIODS_ENTRY = [20, 50]    # M15 — faster, for confirmation

# One shared set of indicator instances (stateless calculators)
_IND = {
    "atr":  ATRCalculator(period=config.ATR_PERIOD),
    "rsi":  RSICalculator(period=14),
    "macd": MACDCalculator(),
    "bb":   BollingerBandsCalculator(period=20, std_dev=2),
    "ma":   MovingAverageCalculator(),
}


class BacktestEngine:

    def __init__(
        self,
        initial_balance:  float = 10_000.0,
        account_currency: str   = "USD",
        fx_rate:          float = 1.0,
        risk_per_trade:   float = None,
        commission:       float = COMMISSION_PER_LOT,
    ):
        """
        initial_balance  — in your account currency (JPY, USD, etc.)
        account_currency — e.g. "JPY" or "USD"
        fx_rate          — units of account currency per 1 USD
                           e.g. 150.0 for a JPY account when USDJPY = 150
                           1.0 for a USD account (default)
        commission       — round-trip commission per lot in USD
        """
        self.initial_balance  = initial_balance
        self.account_currency = account_currency.upper()
        self.fx_rate          = fx_rate          # acct_ccy per USD
        self.risk_per_trade   = risk_per_trade or config.RISK_PER_TRADE
        self.commission       = commission

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, data: Dict[str, pd.DataFrame]) -> dict:
        """
        data must be {"H1": df, "M15": df, "M5": df}
        Each df must have columns: time, open, high, low, close, volume
        'time' must be timezone-aware (UTC) pandas Timestamps.
        """
        h1  = self._ensure_time_col(data["H1"])
        m15 = self._ensure_time_col(data["M15"])
        m5  = self._ensure_time_col(data["M5"]).reset_index(drop=True)

        balance      = self.initial_balance
        equity_curve = []
        trades: List[dict] = []
        active: Optional[dict] = None

        warmup = 200
        total  = len(m5) - warmup
        ccy = self.account_currency
        print(f"\n[*] Backtesting {total:,} M5 bars  "
              f"({m5['time'].iloc[warmup].date()} → {m5['time'].iloc[-1].date()})")
        print(f"    Account: {ccy}  FX rate: 1 USD = {self.fx_rate} {ccy}")
        print(f"    Risk/trade={self.risk_per_trade:.1%}  "
              f"Commission=${self.commission}/lot  "
              f"Spread=${SPREAD_COST}")
        print(f"    RSI bull [{config.RSI_BULL_MIN}–{config.RSI_BULL_MAX}]  "
              f"bear [{config.RSI_BEAR_MIN}–{config.RSI_BEAR_MAX}]  "
              f"Vol≥{config.VOLUME_MIN_RATIO:.0%}\n")

        for i in range(warmup, len(m5)):
            if i % 5000 == 0 and i > warmup:
                pct = (i - warmup) / total * 100
                print(f"    {pct:.0f}%  bar {i:,}/{len(m5):,}  "
                      f"balance={balance:,.0f} {self.account_currency}  trades={len(trades)}")

            bar      = m5.iloc[i]
            bar_time = bar["time"]

            equity_curve.append(balance)

            # ── Manage open position ──────────────────────────────────────────
            if active is not None:
                active, closed = self._manage_position(active, bar)
                for t in closed:
                    balance += t["pnl"]
                    trades.append(t)
                continue   # never enter a new trade while one is open

            # ── Session gate ──────────────────────────────────────────────────
            if config.SESSIONS:
                hour = bar_time.hour
                if not any(s <= hour < e for s, e in config.SESSIONS.values()):
                    continue

            # ── Slice context data for each timeframe ─────────────────────────
            # +1 so analyse functions can drop the forming bar with iloc[:-1]
            h1_slice  = h1[h1["time"] <= bar_time].tail(config.TREND_CANDLES + 1)
            m15_slice = m15[m15["time"] <= bar_time].tail(config.CONFIRM_CANDLES + 1)
            n_entry   = max(config.ENTRY_CANDLES, config.VOLUME_LOOKBACK + 5)
            m5_slice  = m5.iloc[max(0, i - n_entry + 1): i + 1]

            if len(h1_slice) < _MA_PERIODS_TREND[-1] + 6:
                continue
            if len(m15_slice) < 61:
                continue
            if len(m5_slice) < 30:
                continue

            # ── Three-timeframe analysis ──────────────────────────────────────
            trend   = self._analyse_trend(h1_slice)
            confirm = self._analyse_confirm(m15_slice)
            entry_a = self._analyse_entry(m5_slice)

            if not trend or not confirm or not entry_a:
                continue

            sig_data = self._generate_signal(trend, confirm, entry_a)
            if sig_data["signal"] == "NEUTRAL":
                continue

            # ── Sizing & levels ───────────────────────────────────────────────
            sig       = sig_data["signal"]
            atr       = entry_a["atr"]
            if atr == 0:
                continue

            raw_price   = float(bar["close"])
            entry_price = raw_price + SPREAD_COST if sig == "BUY" else raw_price - SPREAD_COST

            is_buy = sig == "BUY"
            sl = entry_price - atr * config.ATR_SL_MULT if is_buy else entry_price + atr * config.ATR_SL_MULT
            tp = entry_price + atr * config.ATR_TP_MULT if is_buy else entry_price - atr * config.ATR_TP_MULT

            risk_dist = abs(entry_price - sl)
            if risk_dist == 0:
                continue
            rr = abs(tp - entry_price) / risk_dist
            if rr < config.MIN_RR_RATIO - 0.001:
                continue

            # Convert account balance to USD for lot sizing
            # (gold P&L is always USD; fx_rate = acct_ccy per 1 USD)
            balance_usd = balance / self.fx_rate
            risk_amount = balance_usd * self.risk_per_trade
            raw_lots    = risk_amount / (risk_dist * CONTRACT_SIZE)
            lots        = round((raw_lots // LOT_STEP) * LOT_STEP, 8)
            lots        = max(MIN_LOT, min(lots, MAX_LOT))

            active = {
                "time":            bar_time,
                "signal":          sig,
                "entry":           entry_price,
                "sl":              sl,
                "tp":              tp,
                "initial_sl":      sl,
                "atr":             atr,
                "lots":            lots,
                "remaining_lots":  lots,
                "risk_amount":     round(risk_amount, 2),
                "rr":              round(rr, 2),
                "bars_held":       0,
                "partial_done":    False,
                "trail_sl":        sl,
                "partial_pnl":     0.0,
            }

        # Force-close any position still open at end of data
        if active is not None:
            close_price = float(m5.iloc[-1]["close"])
            pnl = (self._calc_pnl(active["signal"], active["entry"],
                                  close_price, active["remaining_lots"])
                   + active["partial_pnl"]
                   - self.commission * active["remaining_lots"] * self.fx_rate)
            trades.append({**active, "pnl": round(pnl, 2),
                           "result": "TIME_EXIT", "exit_price": close_price})
            balance += pnl

        equity_curve.append(balance)

        df_trades = pd.DataFrame(trades)
        if not df_trades.empty:
            df_trades.to_csv("backtest_trades.csv", index=False)
            print(f"\n[*] Trades saved → backtest_trades.csv")

        return self._stats(trades, self.initial_balance, equity_curve)

    # ── Position management (bar-by-bar) ───────────────────────────────────────

    def _manage_position(
        self,
        active: dict,
        bar: pd.Series,
    ) -> Tuple[Optional[dict], List[dict]]:
        """
        Returns (updated_active_or_None, list_of_closed_trade_dicts).

        Processing order per bar:
          1. Check partial TP at 1R (if not done)
          2. Check SL / TP exit using trail_sl BEFORE updating trail
          3. Update trail SL for the next bar
        """
        sig    = active["signal"]
        is_buy = sig == "BUY"
        entry  = active["entry"]
        risk   = abs(entry - active["initial_sl"])
        atr    = active["atr"]

        bar_high = float(bar["high"])
        bar_low  = float(bar["low"])

        one_r_price  = entry + risk       if is_buy else entry - risk
        one_5r_price = entry + 1.5 * risk if is_buy else entry - 1.5 * risk

        closed: List[dict] = []

        # ── 1: Partial TP at 1R ───────────────────────────────────────────────
        if not active["partial_done"]:
            hit_1r = (is_buy  and bar_high >= one_r_price) or \
                     (not is_buy and bar_low  <= one_r_price)
            if hit_1r:
                half = round((active["lots"] / 2 // LOT_STEP) * LOT_STEP, 8)
                half = max(MIN_LOT, half)

                pnl_half = (self._calc_pnl(sig, entry, one_r_price, half)
                            - self.commission * half * self.fx_rate)

                active["partial_pnl"]    = pnl_half
                active["remaining_lots"] = round(active["lots"] - half, 8)
                active["partial_done"]   = True
                active["trail_sl"]       = entry  # breakeven

        # ── 2: Check exit using trail_sl from START of bar ────────────────────
        current_sl = active["trail_sl"]

        hit_sl = (is_buy  and bar_low  <= current_sl) or \
                 (not is_buy and bar_high >= current_sl)
        hit_tp = (is_buy  and bar_high >= active["tp"]) or \
                 (not is_buy and bar_low  <= active["tp"])

        # Same-bar conflict: if partial TP is done we're in profit → favour TP
        # otherwise favour SL (conservative)
        if hit_sl and hit_tp:
            if active["partial_done"]:
                hit_sl = False
            else:
                hit_tp = False

        timeout = active["bars_held"] >= MAX_BARS_HELD

        if hit_tp:
            pnl = (self._calc_pnl(sig, entry, active["tp"], active["remaining_lots"])
                   + active["partial_pnl"]
                   - self.commission * active["remaining_lots"] * self.fx_rate)
            closed.append({**active, "pnl": round(pnl, 2),
                           "result": "WIN", "exit_price": active["tp"]})
            return None, closed

        if hit_sl or timeout:
            exit_price = current_sl if hit_sl else float(bar["close"])
            pnl = (self._calc_pnl(sig, entry, exit_price, active["remaining_lots"])
                   + active["partial_pnl"]
                   - self.commission * active["remaining_lots"] * self.fx_rate)
            result = ("TIME_EXIT" if timeout
                      else ("WIN_BE" if pnl > 0 else "LOSS"))
            closed.append({**active, "pnl": round(pnl, 2),
                           "result": result, "exit_price": exit_price})
            return None, closed

        # ── 3: Update trail SL for NEXT bar ──────────────────────────────────
        if active["partial_done"]:
            at_1_5r = (is_buy  and bar_high >= one_5r_price) or \
                      (not is_buy and bar_low  <= one_5r_price)
            if at_1_5r:
                trail_dist = atr * config.TRAIL_ATR_MULT
                if is_buy:
                    new_trail = bar_high - trail_dist
                    if new_trail > active["trail_sl"]:
                        active["trail_sl"] = new_trail
                else:
                    new_trail = bar_low + trail_dist
                    if new_trail < active["trail_sl"]:
                        active["trail_sl"] = new_trail

        active["bars_held"] += 1
        return active, []

    # ── Analysis (mirrors main_mt5.py) ────────────────────────────────────────

    def _analyse_trend(self, h1_slice: pd.DataFrame) -> Optional[Dict]:
        """
        H1: MA50 / MA200 crossover for trend direction.
        Uses iloc[:-1] to exclude the current forming H1 bar — same as live bot.
        """
        ma_df = _IND["ma"].calculate_multiple_mas(h1_slice["close"], periods=_MA_PERIODS_TREND)
        ana   = _IND["ma"].analyze_latest(
            h1_slice["close"].iloc[:-1], ma_df.iloc[:-1]
        )
        return {
            "trend":   ana["trend"],
            "ma_fast": ana["ma_fast"],
            "ma_slow": ana["ma_slow"],
        }

    def _analyse_confirm(self, m15_slice: pd.DataFrame) -> Optional[Dict]:
        """M15: MA20/MA50 structure + MACD direction to confirm H1 trend."""
        ma_df   = _IND["ma"].calculate_multiple_mas(m15_slice["close"], periods=_MA_PERIODS_ENTRY)
        macd_df = _IND["macd"].calculate_macd(m15_slice)
        ma_ana   = _IND["ma"].analyze_latest(
            m15_slice["close"].iloc[:-1], ma_df.iloc[:-1]
        )
        macd_ana = _IND["macd"].analyze_latest(macd_df)
        return {
            "ma_trend": ma_ana["trend"],
            "macd":     macd_ana["signal"],
        }

    def _analyse_entry(self, m5_slice: pd.DataFrame) -> Optional[Dict]:
        """M5: RSI pullback zone + BB position + volume gate + ATR."""
        df      = m5_slice.copy()
        df["rsi"] = _IND["rsi"].calculate_rsi(df)
        bb_df   = _IND["bb"].calculate_bands(df["close"])
        atr_val = _IND["atr"].get_latest(df)

        rsi_val = (float(df["rsi"].iloc[-1])
                   if not df["rsi"].isna().iloc[-1] else None)
        bb_ana  = _IND["bb"].analyze_latest(df["close"], bb_df)

        # Volume gate — mirrors live bot (VOLUME_MIN_RATIO=0.0 disables it)
        volume_ok = True
        if config.VOLUME_MIN_RATIO > 0 and len(df) >= config.VOLUME_LOOKBACK + 1:
            avg_vol   = float(df["volume"].iloc[-(config.VOLUME_LOOKBACK + 1):-1].mean())
            cur_vol   = float(df["volume"].iloc[-1])
            volume_ok = avg_vol > 0 and (cur_vol / avg_vol) >= config.VOLUME_MIN_RATIO

        return {
            "atr":       atr_val,
            "rsi":       rsi_val,
            "bb":        bb_ana,
            "volume_ok": volume_ok,
        }

    def _generate_signal(
        self,
        trend:   dict,
        confirm: dict,
        entry:   dict,
    ) -> dict:
        """Exact copy of generate_signal() from main_mt5.py."""
        trend_dir = trend["trend"]
        is_bull   = trend_dir in ("STRONG_BULL", "BULL")
        is_bear   = trend_dir in ("STRONG_BEAR", "BEAR")
        rsi       = entry["rsi"]
        score     = 0

        if not entry["volume_ok"]:
            return {"signal": "NEUTRAL", "score": 0}

        signal = "NEUTRAL"

        if is_bull or is_bear:
            ma_bull = confirm["ma_trend"] in ("STRONG_BULL", "BULL")
            ma_bear = confirm["ma_trend"] in ("STRONG_BEAR", "BEAR")

            if is_bull and (ma_bull or confirm["macd"] == "BUY"):
                score += 1
            elif is_bear and (ma_bear or confirm["macd"] == "SELL"):
                score += 1

            if is_bull:
                if rsi is not None and config.RSI_BULL_MIN <= rsi <= config.RSI_BULL_MAX:
                    score += 1
                if entry["bb"].get("position") in ("NEAR_LOWER", "BELOW_LOWER", "WALKING_UP"):
                    score += 1
                signal = "BUY" if score >= 2 else "NEUTRAL"
            else:
                if rsi is not None and config.RSI_BEAR_MIN <= rsi <= config.RSI_BEAR_MAX:
                    score += 1
                if entry["bb"].get("position") in ("NEAR_UPPER", "ABOVE_UPPER", "WALKING_DOWN"):
                    score += 1
                signal = "SELL" if score >= 2 else "NEUTRAL"

        return {"signal": signal, "score": score}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _calc_pnl(self, signal: str, entry: float, exit_price: float, lots: float) -> float:
        """
        Unified P&L in account currency.
        Gold P&L is always USD first, then converted via fx_rate.
        fx_rate = account_currency per 1 USD (e.g. 150 for JPY).
        Commission is in USD/lot and also converted.
        """
        direction  = 1 if signal == "BUY" else -1
        pnl_usd    = direction * (exit_price - entry) * CONTRACT_SIZE * lots
        return pnl_usd * self.fx_rate

    @staticmethod
    def _ensure_time_col(df: pd.DataFrame) -> pd.DataFrame:
        """If time is the index, reset it to a column."""
        if "time" not in df.columns:
            return df.reset_index().rename(columns={"index": "time"})
        return df.copy()

    # ── Statistics ─────────────────────────────────────────────────────────────

    def _stats(
        self,
        trades: List[dict],
        initial: float,
        curve: List[float],
    ) -> dict:
        if not trades:
            return {"total_trades": 0, "message": "No trades taken"}

        df   = pd.DataFrame(trades)
        wins = df[df["pnl"] > 0]
        loss = df[df["pnl"] <= 0]

        # Max drawdown from equity curve
        peak, max_dd = initial, 0.0
        for v in curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Annualised Sharpe:  (avg_pnl / std_pnl) × sqrt(trades_per_year)
        # M5 bars per year ≈ 288/day × 260 days ≈ 74,880
        # trades_per_year = trades / years_in_curve
        bars_per_year   = 74_880
        years_in_data   = len(curve) / bars_per_year
        trades_per_year = len(df) / max(years_in_data, 0.01)
        sharpe = 0.0
        if df["pnl"].std() > 0:
            sharpe = (df["pnl"].mean() / df["pnl"].std()) * (trades_per_year ** 0.5)

        pf = 0.0
        if len(loss) > 0 and loss["pnl"].sum() != 0:
            pf = round(abs(wins["pnl"].sum() / loss["pnl"].sum()), 2)

        # Break down results
        result_counts = df["result"].value_counts().to_dict()

        return {
            "total_trades":  len(df),
            "wins":          len(wins),
            "losses":        len(loss),
            "win_rate":      round(len(wins) / len(df) * 100, 1),
            "profit_factor": pf,
            "total_return":  round((curve[-1] - initial) / initial * 100, 2),
            "final_balance": round(curve[-1], 2),
            "total_pnl":     round(curve[-1] - initial, 2),
            "max_drawdown":  round(max_dd * 100, 2),
            "avg_rr":        round(df["rr"].mean(), 2) if "rr" in df else 0,
            "sharpe":        round(sharpe, 3),
            "avg_trade_pnl": round(df["pnl"].mean(), 2),
            "result_counts": result_counts,
        }

    def print_report(self, stats: dict) -> None:
        line = "=" * 55
        print(f"\n{line}")
        print("   GOLD BOT BACKTEST REPORT")
        print(line)
        if "message" in stats:
            print(f"  {stats['message']}")
            print(line)
            return

        ccy = self.account_currency
        rc  = stats.get("result_counts", {})
        print(f"  Total Trades   : {stats['total_trades']}")
        print(f"  Wins / Losses  : {stats['wins']}W  /  {stats['losses']}L")
        print(f"    WIN           : {rc.get('WIN', 0)}")
        print(f"    WIN_BE        : {rc.get('WIN_BE', 0)}  (closed at breakeven or better)")
        print(f"    LOSS          : {rc.get('LOSS', 0)}")
        print(f"    TIME_EXIT     : {rc.get('TIME_EXIT', 0)}")
        print(f"  Win Rate       : {stats['win_rate']}%")
        print(f"  Profit Factor  : {stats['profit_factor']}")
        print(f"  Avg R:R        : {stats['avg_rr']}")
        print(f"  Avg Trade P&L  : {stats['avg_trade_pnl']:,.0f} {ccy}")
        print(line)
        print(f"  Total Return   : {stats['total_return']}%")
        print(f"  Final Balance  : {stats['final_balance']:,.0f} {ccy}")
        print(f"  Total P&L      : {stats['total_pnl']:,.0f} {ccy}")
        print(f"  Max Drawdown   : {stats['max_drawdown']}%")
        print(f"  Sharpe Ratio   : {stats['sharpe']}  (annualised)")
        print(line)
