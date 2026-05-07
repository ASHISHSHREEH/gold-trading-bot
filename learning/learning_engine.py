"""
LearningEngine — thread-safe orchestrator for the hybrid AI layer.

Coordinates three AI components:
    1. ParameterTuner  — statistical parameter optimisation (runs offline)
    2. SignalClassifier — RandomForest win-probability estimator
    3. RLAgent          — Q-learning action voter

Voting weights (conservative — base strategy always dominates):
    base_score  : 0.60   (normalised rule-based score)
    ml_score    : 0.25   (classifier win probability)
    rl_score    : 0.15   (RL action alignment)

Safety rules:
    • AI can only SUPPRESS trades (veto) — it cannot CREATE trades
    • If base signal is NEUTRAL → decision is always NEUTRAL
    • ML veto threshold: win_probability < 0.35 AND ML is active
    • Joint veto: RL says HOLD AND ml_score < 0.45
    • All vetoes are logged for offline analysis

Integration points (called from main_mt5.py):
    engine.load_models()                  — call once at startup
    engine.ai_vote(signal, entry, ...)    — call after generate_signal()
    engine.on_trade_close(trade_result)   — call when a position closes
    engine.shutdown()                     — call in finally block
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Voting weights ─────────────────────────────────────────────────────────────
W_BASE = 0.60
W_ML   = 0.25
W_RL   = 0.15

# ── Veto thresholds ────────────────────────────────────────────────────────────
ML_HARD_VETO_BELOW     = 0.35   # ml active + prob < this → veto
ML_SOFT_VETO_BELOW     = 0.45   # used in joint veto with RL
RL_HOLD_JOINT_VETO     = True   # RL=HOLD + ml_soft → veto

# ── Retraining schedule ────────────────────────────────────────────────────────
TUNE_EVERY_N_SESSIONS  = 5      # run param_tuner every N bot sessions
TUNE_MIN_NEW_TRADES    = 20     # or when N new trades arrived since last tune


@dataclass
class AIDecision:
    """Structured output of the ai_vote() call."""
    base_score:     float            # raw rule-based score (0–6+)
    ml_score:       float            # win probability from classifier (0–1)
    rl_vote:        str              # "BUY" | "SELL" | "HOLD"
    ai_confidence:  float            # composite 0–10
    decision:       str              # "BUY" | "SELL" | "NEUTRAL" (HOLD maps to NEUTRAL)
    ml_active:      bool
    veto_reason:    Optional[str]
    feature_importance: Dict[str, float] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_score":        self.base_score,
            "ml_score":          round(self.ml_score, 4),
            "rl_vote":           self.rl_vote,
            "ai_confidence":     round(self.ai_confidence, 2),
            "decision":          self.decision,
            "ml_active":         self.ml_active,
            "veto_reason":       self.veto_reason,
        }


class LearningEngine:
    """
    Thread-safe AI orchestrator.

    All public methods are safe to call from the main bot loop;
    retraining runs on a background daemon thread so it never
    blocks the scan cycle.
    """

    def __init__(self, db_path: str = "data/trading_mt5.db") -> None:
        self.db_path  = db_path
        self._lock    = threading.Lock()
        self._ready   = False

        # Component references (populated by load_models)
        self._tuner:      Optional[object] = None   # ParameterTuner
        self._classifier: Optional[object] = None   # SignalClassifier
        self._rl:         Optional[object] = None   # RLAgent

        # Retraining state
        self._session_count       = 0
        self._trades_at_last_tune = 0
        self._retrain_thread: Optional[threading.Thread] = None

        # Rolling buffer for drift detection
        self._recent_features: List[Dict[str, Any]] = []
        self._max_recent       = 100

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    def load_models(self) -> None:
        """
        Initialise all AI components, load persisted state.
        Call once at bot startup — safe to call if sklearn is missing.
        """
        try:
            from learning.param_tuner      import ParameterTuner
            from learning.signal_classifier import SignalClassifier
            from learning.rl_agent          import RLAgent

            self._tuner      = ParameterTuner(self.db_path)
            self._classifier = SignalClassifier(self.db_path)
            self._rl         = RLAgent()
            self._ready      = True
            logger.info("LearningEngine: all components loaded.")
        except Exception as exc:
            logger.error("LearningEngine.load_models failed — %s. AI layer disabled.", exc, exc_info=True)
            self._ready = False

    def shutdown(self) -> None:
        """Persist Q-table and wait for any running retrain to finish."""
        if self._rl is not None:
            try:
                self._rl.save()
            except Exception as exc:
                logger.warning("LearningEngine.shutdown: RL save failed — %s", exc)
        if self._retrain_thread and self._retrain_thread.is_alive():
            logger.info("LearningEngine: waiting for background retrain...")
            self._retrain_thread.join(timeout=30)
        logger.info("LearningEngine: shutdown complete.")

    # ── Core voting ─────────────────────────────────────────────────────────────

    def ai_vote(
        self,
        signal_data: Dict[str, Any],
        entry_data:  Dict[str, Any],
        htf:         Dict[str, Any],
        trend:       Dict[str, Any],
        confirm:     Dict[str, Any],
        timing:      Dict[str, Any],
        session:     Optional[str] = None,
    ) -> AIDecision:
        """
        Combine rule-based score, ML probability, and RL vote into
        a single AI decision.

        Args:
            signal_data : output of generate_signal()
            entry_data  : output of analyse_entry()
            htf         : output of analyse_htf()
            trend       : output of analyse_trend()
            confirm     : output of analyse_confirm()
            timing      : output of analyse_timing()
            session     : current session name (from current_session())

        Returns:
            AIDecision — always returns something valid, never raises.
        """
        base_signal = signal_data.get("signal", "NEUTRAL")
        base_score  = float(signal_data.get("score", 0))

        # Hard rule: AI never creates a trade from a NEUTRAL base signal
        if base_signal == "NEUTRAL":
            return AIDecision(
                base_score    = base_score,
                ml_score      = 0.5,
                rl_vote       = "HOLD",
                ai_confidence = 0.0,
                decision      = "NEUTRAL",
                ml_active     = False,
                veto_reason   = None,
            )

        if not self._ready:
            return self._passthrough(base_signal, base_score)

        # ── Build feature dict for ML + RL ──────────────────────────────────────
        features = self._build_features(
            signal_data, entry_data, htf, trend, confirm, timing, session
        )
        self._buffer_features(features)

        # ── ML prediction ───────────────────────────────────────────────────────
        ml_result  = self._safe_classify(features)
        ml_score   = float(ml_result.get("ml_score", 0.5))
        ml_active  = bool(ml_result.get("active", False))

        # ── RL vote ─────────────────────────────────────────────────────────────
        market_snapshot = {
            "h1_trend": trend.get("trend", "NEUTRAL"),
            "h4_trend": htf.get("trend", "NEUTRAL"),
            "rsi":      entry_data.get("rsi"),
            "atr":      entry_data.get("atr"),
            "session":  session,
        }
        rl_result = self._safe_rl_vote(market_snapshot)
        rl_vote   = rl_result.get("action", "HOLD")

        # ── Composite confidence ─────────────────────────────────────────────────
        base_norm  = min(base_score / 6.0, 1.0)   # normalise to 0–1
        rl_norm    = self._rl_to_score(rl_vote, base_signal)
        composite  = W_BASE * base_norm + W_ML * ml_score + W_RL * rl_norm
        confidence = round(composite * 10.0, 2)    # scale to 0–10

        # ── Veto logic (AI can only suppress, never create) ──────────────────────
        veto_reason: Optional[str] = None

        # Hard ML veto: classifier is active and very confident it's a loser
        if ml_active and ml_score < ML_HARD_VETO_BELOW:
            veto_reason = f"ML hard veto: win_prob={ml_score:.2f} < {ML_HARD_VETO_BELOW}"

        # Joint veto: RL says HOLD AND ML is soft-low
        elif (RL_HOLD_JOINT_VETO and rl_vote == "HOLD" and ml_active
              and ml_score < ML_SOFT_VETO_BELOW):
            veto_reason = (
                f"Joint veto: RL=HOLD + ml_score={ml_score:.2f} < {ML_SOFT_VETO_BELOW}"
            )

        decision = "NEUTRAL" if veto_reason else base_signal

        if veto_reason:
            logger.info(
                "LearningEngine VETO | %s → NEUTRAL | %s | base=%.1f ml=%.3f rl=%s",
                base_signal, veto_reason, base_score, ml_score, rl_vote,
            )
        else:
            logger.debug(
                "LearningEngine vote | %s | conf=%.2f | ml=%.3f | rl=%s",
                decision, confidence, ml_score, rl_vote,
            )

        return AIDecision(
            base_score          = base_score,
            ml_score            = ml_score,
            rl_vote             = rl_vote,
            ai_confidence       = confidence,
            decision            = decision,
            ml_active           = ml_active,
            veto_reason         = veto_reason,
            feature_importance  = ml_result.get("feature_importance", {}),
            meta                = {"rl_q_values": rl_result.get("q_values", []), "epsilon": rl_result.get("epsilon", 0)},
        )

    # ── Online learning update ───────────────────────────────────────────────────

    def on_trade_close(
        self,
        trade_result:    Dict[str, Any],
        entry_market:    Optional[Dict[str, Any]] = None,
        current_market:  Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Called after a trade closes.  Updates RL agent online and checks
        whether ML / param tuner should retrain.

        Args:
            trade_result   : {ticket, profit, rr_achieved, direction, h1_trend,
                              close_time_epoch, symbol}
            entry_market   : market snapshot at trade entry (for RL prev state)
            current_market : current market snapshot (for RL next state)
        """
        if not self._ready:
            return

        # ── RL update ────────────────────────────────────────────────────────────
        if self._rl is not None and entry_market and current_market:
            try:
                reward = self._rl.compute_reward(trade_result)
                action = "BUY" if trade_result.get("direction") == "BUY" else "SELL"
                self._rl.update(entry_market, action, reward, current_market)
                logger.debug(
                    "LearningEngine: RL updated | ticket=%s profit=%.2f reward=%.3f",
                    trade_result.get("ticket"), trade_result.get("profit", 0), reward,
                )
            except Exception as exc:
                logger.error("LearningEngine: RL update error — %s", exc)

        # ── Check retraining schedule ─────────────────────────────────────────────
        self._maybe_retrain_async()

    def on_session_end(self) -> None:
        """Call at bot session end to increment session counter and save RL state."""
        self._session_count += 1
        if self._rl is not None:
            try:
                self._rl.save()
            except Exception as exc:
                logger.warning("LearningEngine: RL save at session end failed — %s", exc)
        self._maybe_retrain_async()

    # ── Param hot-reload ─────────────────────────────────────────────────────────

    def get_live_params(self) -> Dict[str, Any]:
        """
        Return current learned parameters.  Call at startup and optionally
        after each retrain to pick up improved RSI zones etc.
        Returns DEFAULTS if tuner not ready.
        """
        if self._tuner is None:
            return {}
        try:
            return self._tuner.load()
        except Exception:
            return {}

    # ── Drift diagnostic ────────────────────────────────────────────────────────

    def drift_score(self) -> float:
        """PSI-based drift metric.  > 0.2 suggests model retraining is urgent."""
        if self._classifier is None:
            return 0.0
        try:
            with self._lock:
                recent = list(self._recent_features)
            return float(self._classifier.drift_score(recent))
        except Exception:
            return 0.0

    # ── Internal helpers ─────────────────────────────────────────────────────────

    def _passthrough(self, signal: str, score: float) -> AIDecision:
        """Return a pass-through decision when AI is not ready."""
        return AIDecision(
            base_score    = score,
            ml_score      = 0.5,
            rl_vote       = signal,
            ai_confidence = round((score / 6.0) * 10.0, 2),
            decision      = signal,
            ml_active     = False,
            veto_reason   = None,
        )

    @staticmethod
    def _build_features(
        signal_data: Dict[str, Any],
        entry_data:  Dict[str, Any],
        htf:         Dict[str, Any],
        trend:       Dict[str, Any],
        confirm:     Dict[str, Any],
        timing:      Dict[str, Any],
        session:     Optional[str],
    ) -> Dict[str, Any]:
        """Assemble all ML features into a flat dict."""
        from datetime import datetime, timezone
        hour = datetime.now(timezone.utc).hour
        return {
            "macd_signal":   confirm.get("macd", "NEUTRAL"),
            "bb_position":   (entry_data.get("bb") or {}).get("position", "MIDDLE"),
            "htf_trend":     htf.get("trend", "NEUTRAL"),
            "h1_trend":      trend.get("trend", "NEUTRAL"),
            "m15_trend":     confirm.get("ma_trend", "NEUTRAL"),
            "m1_direction":  timing.get("direction", "NEUTRAL"),
            "rsi":           entry_data.get("rsi") or 50.0,
            "atr":           entry_data.get("atr") or 0.0,
            "spread":        entry_data.get("spread") or 0.0,
            "volume_ratio":  entry_data.get("volume_ratio") or 1.0,
            "base_score":    float(signal_data.get("score", 0)),
            "session_hour":  float(hour),
            "session":       session,
        }

    def _buffer_features(self, features: Dict[str, Any]) -> None:
        with self._lock:
            self._recent_features.append(features)
            if len(self._recent_features) > self._max_recent:
                self._recent_features.pop(0)

    def _safe_classify(self, features: Dict[str, Any]) -> Dict[str, Any]:
        if self._classifier is None:
            return {"ml_score": 0.5, "active": False}
        try:
            return self._classifier.predict(features)
        except Exception as exc:
            logger.error("LearningEngine: classifier.predict error — %s", exc)
            return {"ml_score": 0.5, "active": False}

    def _safe_rl_vote(self, market: Dict[str, Any]) -> Dict[str, Any]:
        if self._rl is None:
            return {"action": "HOLD", "q_values": [0, 0, 0]}
        try:
            return self._rl.vote(market)
        except Exception as exc:
            logger.error("LearningEngine: rl.vote error — %s", exc)
            return {"action": "HOLD", "q_values": [0, 0, 0]}

    @staticmethod
    def _rl_to_score(rl_vote: str, base_signal: str) -> float:
        """Convert RL action → 0-1 alignment score relative to base signal."""
        if rl_vote == base_signal:   return 1.0
        if rl_vote == "HOLD":        return 0.5
        return 0.0   # opposite direction

    def _maybe_retrain_async(self) -> None:
        """Spawn background retrain if due; skip if one is already running."""
        if self._retrain_thread and self._retrain_thread.is_alive():
            return   # previous retrain still running — don't stack

        should = (
            self._session_count > 0 and self._session_count % TUNE_EVERY_N_SESSIONS == 0
        )
        if not should:
            closed_count = self._get_closed_trade_count()
            should = (closed_count - self._trades_at_last_tune) >= TUNE_MIN_NEW_TRADES

        if should:
            self._retrain_thread = threading.Thread(
                target=self._retrain_worker,
                name="ai-retrain",
                daemon=True,
            )
            self._retrain_thread.start()
            logger.info("LearningEngine: background retrain started.")

    def _retrain_worker(self) -> None:
        """Runs on background daemon thread — retrains classifier and tuner."""
        start = time.time()
        try:
            closed_count = self._get_closed_trade_count()

            # ── Param tuner ────────────────────────────────────────────────────
            if self._tuner is not None:
                self._tuner.run()

            # ── ML classifier ──────────────────────────────────────────────────
            if self._classifier is not None and self._classifier.should_retrain(closed_count):
                self._classifier.train()

            self._trades_at_last_tune = closed_count
            logger.info(
                "LearningEngine: retrain complete in %.1fs | trades=%d",
                time.time() - start, closed_count,
            )
        except Exception as exc:
            logger.error("LearningEngine: retrain_worker error — %s", exc, exc_info=True)

    def _get_closed_trade_count(self) -> int:
        import sqlite3 as _sqlite3
        try:
            conn = _sqlite3.connect(self.db_path)
            cur  = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE close_time IS NOT NULL"
            )
            return int(cur.fetchone()[0])
        except Exception:
            return 0
        finally:
            conn.close()
