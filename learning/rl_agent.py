"""
RLAgent — tabular Q-learning reinforcement learning agent.

Designed for low-resource deployment (VPS, Raspberry Pi):
  • No GPU, no heavy framework dependencies
  • Full Q-table fits in < 1 MB RAM (≤ 5 400 states × 3 actions × 4 bytes)
  • Thread-safe via threading.Lock
  • Persistent: saves/loads Q-table as pickle

State space (6 dimensions, 5×5×3×5×3×3 = 3 375 total states):
    trend_bucket       : STRONG_BEAR / BEAR / NEUTRAL / BULL / STRONG_BULL
    rsi_bucket         : OVERSOLD / LOW / MID / HIGH / OVERBOUGHT
    volatility_bucket  : LOW / MEDIUM / HIGH   (relative to recent ATR history)
    session_bucket     : DEAD / TOKYO / LONDON / NEWYORK / OVERLAP
    prev_outcome_bucket: NONE / WIN / LOSS
    regime_bucket      : RANGING / TRENDING / VOLATILE

Actions: HOLD=0, BUY=1, SELL=2

Reward shaping:
    WIN  → +rr_achieved (capped at reward_cap)
    LOSS → -1.0
    Consecutive-loss drawdown penalty (activates at ≥5 losses)
    Trend-alignment bonus (+0.2)
    Revenge-trade penalty if second trade opened within 5 min of a loss

Exploration: epsilon-greedy with exponential decay (ε_start=0.30 → ε_end=0.05)
"""

from __future__ import annotations

import logging
import math
import pickle
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

Q_TABLE_PATH = Path("learning/q_table.pkl")

# ── State-space enumerations ────────────────────────────────────────────────────

class TrendBucket(IntEnum):
    STRONG_BEAR = 0
    BEAR        = 1
    NEUTRAL     = 2
    BULL        = 3
    STRONG_BULL = 4

class RSIBucket(IntEnum):
    OVERSOLD   = 0   # rsi < 30
    LOW        = 1   # 30 – 45
    MID        = 2   # 45 – 55
    HIGH       = 3   # 55 – 70
    OVERBOUGHT = 4   # > 70

class VolatilityBucket(IntEnum):
    LOW    = 0
    MEDIUM = 1
    HIGH   = 2

class SessionBucket(IntEnum):
    DEAD    = 0
    TOKYO   = 1
    LONDON  = 2
    NEWYORK = 3
    OVERLAP = 4   # London / NY 13–16 UTC

class OutcomeBucket(IntEnum):
    NONE = 0
    WIN  = 1
    LOSS = 2

class RegimeBucket(IntEnum):
    RANGING  = 0
    TRENDING = 1
    VOLATILE = 2

class Action(IntEnum):
    HOLD = 0
    BUY  = 1
    SELL = 2

# State is a plain tuple for O(1) dict lookup
State = Tuple[int, int, int, int, int, int]


@dataclass
class RLConfig:
    alpha:            float = 0.10    # Q-learning rate
    gamma:            float = 0.90    # discount factor
    epsilon_start:    float = 0.30    # initial exploration probability
    epsilon_end:      float = 0.05    # minimum exploration probability
    epsilon_decay:    float = 500.0   # effective episode half-life
    reward_cap:       float = 3.0     # clip rewards to ±reward_cap
    drawdown_penalty: float = 0.50    # penalty per 5 consecutive losses
    trend_bonus:      float = 0.20    # bonus for trend-aligned trade
    revenge_window_s: float = 300.0   # seconds — threshold for revenge-trade detection
    atr_history_len:  int   = 200     # rolling window for volatility percentiles


class RLAgent:
    """
    Lightweight Q-learning agent that votes BUY / SELL / HOLD on each signal.

    The vote is advisory only — it is one input to the learning_engine's
    weighted ensemble.  The agent is updated online after each trade closes.
    """

    def __init__(self, config: Optional[RLConfig] = None) -> None:
        self.cfg  = config or RLConfig()
        self._lock = threading.Lock()

        # Q-table: state → float32 array of shape (3,)
        self._q: Dict[State, np.ndarray] = {}
        self._episode            = 0
        self._epsilon            = self.cfg.epsilon_start

        # Running state
        self._prev_outcome       = OutcomeBucket.NONE
        self._consecutive_losses = 0
        self._last_loss_epoch: Optional[float] = None
        self._atr_history: list  = []   # rolling window for volatility bucketing

        self._load()
        logger.info(
            "RLAgent ready | episodes=%d | ε=%.3f | q_states=%d",
            self._episode, self._epsilon, len(self._q),
        )

    # ── Public API ──────────────────────────────────────────────────────────────

    def vote(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return action vote for current market state.

        Args:
            market: {
                "h1_trend": str,   "h4_trend": str,
                "rsi":      float, "atr":      float,
                "session":  str,
            }

        Returns:
            {
                "action":   "BUY" | "SELL" | "HOLD",
                "q_values": [hold, buy, sell],
                "epsilon":  float,
                "state":    tuple,
            }
        """
        state = self._encode_state(market)
        with self._lock:
            if np.random.random() < self._epsilon:
                action = Action(np.random.randint(0, 3))
            else:
                action = Action(int(np.argmax(self._get_q(state))))

        return {
            "action":   action.name,
            "q_values": self._get_q(state).tolist(),
            "epsilon":  round(self._epsilon, 4),
            "state":    state,
        }

    def update(
        self,
        prev_market:  Dict[str, Any],
        action_taken: str,
        reward:       float,
        next_market:  Dict[str, Any],
    ) -> None:
        """
        Single-step Q-learning update.

        Q(s,a) ← Q(s,a) + α · [r + γ · max_a′ Q(s′,a′) − Q(s,a)]
        """
        s  = self._encode_state(prev_market)
        s_ = self._encode_state(next_market)
        try:
            a = Action[action_taken.upper()]
        except KeyError:
            a = Action.HOLD

        with self._lock:
            q_s  = self._get_q(s)
            q_s_ = self._get_q(s_)
            td   = reward + self.cfg.gamma * float(np.max(q_s_)) - q_s[a]
            q_s[a] += self.cfg.alpha * td
            self._q[s] = q_s

            self._episode += 1
            self._epsilon  = self._decay_epsilon(self._episode)

        logger.debug(
            "RLAgent update | s=%s a=%s r=%.3f td=%.4f ε=%.4f",
            s, action_taken, reward, td, self._epsilon,
        )

    def compute_reward(self, trade: Dict[str, Any]) -> float:
        """
        Shape reward from trade outcome dict.

        Args:
            trade: {
                "profit":           float,
                "rr_achieved":      float,   # realised R:R (can be < configured TP)
                "direction":        str,
                "h1_trend":         str,
                "close_time_epoch": float,   # unix timestamp of close
            }
        """
        profit     = float(trade.get("profit") or 0.0)
        rr         = float(trade.get("rr_achieved") or 0.0)
        direction  = str(trade.get("direction") or "")
        h1_trend   = str(trade.get("h1_trend") or "")
        close_ts   = float(trade.get("close_time_epoch") or time.time())

        is_win = profit > 0

        if is_win:
            reward                   = min(rr, self.cfg.reward_cap)
            self._prev_outcome       = OutcomeBucket.WIN
            self._consecutive_losses = 0
        else:
            reward                    = -1.0
            self._prev_outcome        = OutcomeBucket.LOSS
            self._consecutive_losses += 1
            self._last_loss_epoch     = close_ts

        # Consecutive-loss drawdown penalty (progressive, caps at 1.5)
        if self._consecutive_losses >= 5:
            penalty = self.cfg.drawdown_penalty * (self._consecutive_losses / 5.0)
            reward -= min(penalty, 1.5)

        # Revenge-trade penalty: win arrived quickly after a loss
        if (is_win and self._last_loss_epoch is not None
                and (close_ts - self._last_loss_epoch) < self.cfg.revenge_window_s):
            reward -= 0.3   # discourage rapid re-entry after a loss

        # Trend-alignment bonus
        aligned = (
            (direction == "BUY"  and h1_trend in ("BULL",  "STRONG_BULL")) or
            (direction == "SELL" and h1_trend in ("BEAR",  "STRONG_BEAR"))
        )
        if aligned:
            reward += self.cfg.trend_bonus

        clipped = float(np.clip(reward, -self.cfg.reward_cap, self.cfg.reward_cap))
        logger.debug(
            "RLAgent reward | direction=%s h1=%s win=%s rr=%.2f → r=%.3f",
            direction, h1_trend, is_win, rr, clipped,
        )
        return clipped

    def save(self) -> None:
        Q_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "q":                   self._q,
                "episode":             self._episode,
                "epsilon":             self._epsilon,
                "prev_outcome":        int(self._prev_outcome),
                "consecutive_losses":  self._consecutive_losses,
                "last_loss_epoch":     self._last_loss_epoch,
                "atr_history":         self._atr_history[-self.cfg.atr_history_len:],
            }
        with open(Q_TABLE_PATH, "wb") as fh:
            pickle.dump(payload, fh, protocol=4)
        logger.debug("RLAgent: Q-table saved (%d states, episode=%d)", len(self._q), self._episode)

    # ── State encoding ──────────────────────────────────────────────────────────

    def _encode_state(self, market: Dict[str, Any]) -> State:
        trend  = self._enc_trend(market.get("h1_trend", "NEUTRAL"))
        rsi    = self._enc_rsi(market.get("rsi"))
        vol    = self._enc_volatility(market.get("atr"))
        sess   = self._enc_session(market.get("session"))
        regime = self._enc_regime(market)
        return (trend, rsi, vol, sess, int(self._prev_outcome), regime)

    @staticmethod
    def _enc_trend(trend: str) -> int:
        return int({
            "STRONG_BEAR": TrendBucket.STRONG_BEAR,
            "BEAR":        TrendBucket.BEAR,
            "NEUTRAL":     TrendBucket.NEUTRAL,
            "BULL":        TrendBucket.BULL,
            "STRONG_BULL": TrendBucket.STRONG_BULL,
        }.get(trend, TrendBucket.NEUTRAL))

    @staticmethod
    def _enc_rsi(rsi: Optional[float]) -> int:
        if rsi is None:
            return int(RSIBucket.MID)
        if rsi < 30:  return int(RSIBucket.OVERSOLD)
        if rsi < 45:  return int(RSIBucket.LOW)
        if rsi < 55:  return int(RSIBucket.MID)
        if rsi < 70:  return int(RSIBucket.HIGH)
        return int(RSIBucket.OVERBOUGHT)

    def _enc_volatility(self, atr: Optional[float]) -> int:
        if atr is not None:
            self._atr_history.append(float(atr))
            if len(self._atr_history) > self.cfg.atr_history_len:
                self._atr_history.pop(0)

        if atr is None or len(self._atr_history) < 10:
            return int(VolatilityBucket.MEDIUM)

        p33 = float(np.percentile(self._atr_history, 33))
        p66 = float(np.percentile(self._atr_history, 66))
        if atr <= p33:  return int(VolatilityBucket.LOW)
        if atr <= p66:  return int(VolatilityBucket.MEDIUM)
        return int(VolatilityBucket.HIGH)

    @staticmethod
    def _enc_session(session: Optional[str]) -> int:
        return int({
            "Tokyo":   SessionBucket.TOKYO,
            "London":  SessionBucket.LONDON,
            "NewYork": SessionBucket.NEWYORK,
            "Overlap": SessionBucket.OVERLAP,
            "Always":  SessionBucket.LONDON,
        }.get(session or "", SessionBucket.DEAD))

    @staticmethod
    def _enc_regime(market: Dict[str, Any]) -> int:
        trend = market.get("h1_trend", "NEUTRAL")
        atr   = market.get("atr")
        if trend in ("BULL", "STRONG_BULL", "BEAR", "STRONG_BEAR"):
            return int(RegimeBucket.TRENDING)
        # Crude volatility proxy: ATR > 15 (reasonable for XAUUSD M5)
        if atr is not None and float(atr) > 15.0:
            return int(RegimeBucket.VOLATILE)
        return int(RegimeBucket.RANGING)

    # ── Q-table helpers ─────────────────────────────────────────────────────────

    def _get_q(self, state: State) -> np.ndarray:
        if state not in self._q:
            self._q[state] = np.zeros(3, dtype=np.float32)
        return self._q[state]

    def _decay_epsilon(self, episode: int) -> float:
        return self.cfg.epsilon_end + (
            (self.cfg.epsilon_start - self.cfg.epsilon_end)
            * math.exp(-episode / self.cfg.epsilon_decay)
        )

    # ── Persistence ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not Q_TABLE_PATH.exists():
            return
        try:
            with open(Q_TABLE_PATH, "rb") as fh:
                data = pickle.load(fh)
            self._q                   = data.get("q", {})
            self._episode             = int(data.get("episode", 0))
            self._epsilon             = float(data.get("epsilon", self.cfg.epsilon_start))
            self._prev_outcome        = OutcomeBucket(int(data.get("prev_outcome", 0)))
            self._consecutive_losses  = int(data.get("consecutive_losses", 0))
            self._last_loss_epoch     = data.get("last_loss_epoch")
            self._atr_history         = list(data.get("atr_history", []))
            logger.info(
                "RLAgent: loaded Q-table (%d states, episode=%d, ε=%.3f)",
                len(self._q), self._episode, self._epsilon,
            )
        except Exception as exc:
            logger.warning("RLAgent: failed to load Q-table — %s. Starting fresh.", exc)
            self._q = {}
