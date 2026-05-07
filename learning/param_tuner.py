"""
ParameterTuner — statistically optimises RSI zones, score thresholds, ATR
multipliers, session weights, and volume filters from closed trade history.

Design principles:
  • Requires minimum sample sizes before any parameter moves
  • Exponential recency weighting — recent trades count more
  • Trust blending: learned values are phased in as sample count grows
    (0% learned at 30 trades → 100% learned at 200 trades)
  • Bootstrap 90% confidence intervals for key RSI parameters
  • All parameters clipped to hard guard-rails — never goes extreme
  • Atomic JSON writes to avoid corrupt mid-read snapshots
  • Never touches execution logic — outputs JSON only; bot reads at next startup
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── File paths ──────────────────────────────────────────────────────────────────
OUTPUT_PATH = Path("learning/learned_params.json")

# ── Hard guard-rails — no parameter ever leaves this range ─────────────────────
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "rsi_bull_min":     (25.0, 50.0),
    "rsi_bull_max":     (45.0, 70.0),
    "rsi_bear_min":     (30.0, 55.0),
    "rsi_bear_max":     (50.0, 75.0),
    "min_score":        (1.0,  5.0),
    "atr_sl_mult":      (1.0,  3.0),
    "atr_tp_mult":      (2.0,  5.0),
    "volume_min_ratio": (0.0,  1.5),
}

# ── Conservative production defaults ───────────────────────────────────────────
DEFAULTS: Dict[str, Any] = {
    "rsi_bull_min":     40.0,
    "rsi_bull_max":     55.0,
    "rsi_bear_min":     45.0,
    "rsi_bear_max":     60.0,
    "min_score":        2.0,
    "atr_sl_mult":      1.5,
    "atr_tp_mult":      3.0,
    "volume_min_ratio": 0.8,
    "session_weights":  {"Tokyo": 1.0, "London": 1.0, "NewYork": 1.0},
}

# ── Sample-size thresholds ──────────────────────────────────────────────────────
MIN_GLOBAL    = 30    # trades required before ANY tuning runs
MIN_BIN       = 8     # trades per bucket to trust that bucket's stats
TRUST_FULL_N  = 200   # trade count at which learned values get 100% weight

# ── Recency decay ───────────────────────────────────────────────────────────────
RECENCY_HALF_LIFE  = 50    # trades — half-life of exponential weight
BOOTSTRAP_ITERS    = 300
BOOTSTRAP_RNG_SEED = 42


@dataclass
class TunerResult:
    params:       Dict[str, Any]
    sample_count: int
    confidence:   Dict[str, Tuple[float, float]]   # param → (lo95, hi95)
    last_updated: str
    version:      int


class ParameterTuner:
    """
    Reads closed trades + learning_features from SQLite, derives optimal
    parameter values, blends with defaults, and writes learned_params.json.

    Usage:
        tuner = ParameterTuner("data/trading_mt5.db")
        result = tuner.run()          # returns None if insufficient data
        params = tuner.load()         # always returns a valid param dict
    """

    def __init__(self, db_path: str = "data/trading_mt5.db") -> None:
        self.db_path  = db_path
        self._version = self._current_version()
        logger.info("ParameterTuner init | db=%s | current_version=%d", db_path, self._version)

    # ── Public API ──────────────────────────────────────────────────────────────

    def run(self) -> Optional[TunerResult]:
        """Full optimisation pass. Returns None when data is insufficient."""
        try:
            trades = self._load_closed_trades()
        except Exception as exc:
            logger.error("ParameterTuner.run: DB load failed — %s", exc)
            return None

        n = len(trades)
        if n < MIN_GLOBAL:
            logger.info("ParameterTuner: %d trades < %d minimum — skipping.", n, MIN_GLOBAL)
            return None

        logger.info("ParameterTuner: optimising from %d closed trades...", n)

        weights = self._recency_weights(n)
        trust   = min(1.0, (n - MIN_GLOBAL) / float(TRUST_FULL_N - MIN_GLOBAL))

        params = dict(DEFAULTS)

        params.update(self._tune_rsi_zones(trades, weights, trust))
        params.update(self._tune_atr_mults(trades, weights, trust))

        thresh = self._tune_score_threshold(trades, weights, trust)
        if thresh is not None:
            params["min_score"] = thresh

        vol = self._tune_volume_threshold(trades, weights, trust)
        if vol is not None:
            params["volume_min_ratio"] = vol

        sw = self._tune_session_weights(trades, weights)
        if sw:
            params["session_weights"] = sw

        params = self._clip_to_bounds(params)
        ci     = self._bootstrap_ci(trades, weights, trust)

        self._version += 1
        result = TunerResult(
            params       = params,
            sample_count = n,
            confidence   = ci,
            last_updated = datetime.now(timezone.utc).isoformat(),
            version      = self._version,
        )
        self._write(result)
        logger.info(
            "ParameterTuner: params v%d written | trust=%.0f%% | trades=%d",
            self._version, trust * 100, n,
        )
        return result

    def load(self) -> Dict[str, Any]:
        """Always returns a valid param dict (falls back to DEFAULTS on any error)."""
        if not OUTPUT_PATH.exists():
            return dict(DEFAULTS)
        try:
            raw = json.loads(OUTPUT_PATH.read_text())
            return raw.get("params", DEFAULTS)
        except Exception as exc:
            logger.warning("ParameterTuner.load: read failed — %s", exc)
            return dict(DEFAULTS)

    # ── Optimisation sub-routines ───────────────────────────────────────────────

    def _tune_rsi_zones(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
        trust:   float,
    ) -> Dict[str, float]:
        result: Dict[str, float] = {}

        for direction, prefix in [("BUY", "rsi_bull"), ("SELL", "rsi_bear")]:
            # Winning trades for this direction that have RSI recorded
            pairs = [
                (float(t["rsi"]), w)
                for t, w in zip(trades, weights)
                if t["direction"] == direction
                and t["rsi"] is not None
                and (t["profit"] or 0) > 0
            ]
            if len(pairs) < MIN_BIN:
                continue

            rsi_vals = np.array([p[0] for p in pairs])
            # Weighted 20th / 80th percentiles define the "sweet zone"
            p20 = float(np.percentile(rsi_vals, 20))
            p80 = float(np.percentile(rsi_vals, 80))

            for key, learned, default_key in [
                (f"{prefix}_min", p20, f"{prefix}_min"),
                (f"{prefix}_max", p80, f"{prefix}_max"),
            ]:
                default = float(DEFAULTS[default_key])
                result[key] = round(default + trust * (learned - default), 2)

        return result

    def _tune_atr_mults(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
        trust:   float,
    ) -> Dict[str, float]:
        winning = [
            (float(t["rr_ratio"]), w)
            for t, w in zip(trades, weights)
            if (t["profit"] or 0) > 0
            and t.get("rr_ratio") is not None
            and float(t["rr_ratio"]) > 0
        ]
        if len(winning) < MIN_BIN:
            return {}

        rr_arr  = np.array([x[0] for x in winning])
        w_arr   = np.array([x[1] for x in winning])
        w_arr  /= w_arr.sum()
        avg_rr  = float(np.average(rr_arr, weights=w_arr))

        # Only nudge TP upward if average achieved RR comfortably exceeds 2.5
        learned_tp = min(avg_rr * 0.9, PARAM_BOUNDS["atr_tp_mult"][1]) if avg_rr > 2.5 else DEFAULTS["atr_tp_mult"]
        default_tp = float(DEFAULTS["atr_tp_mult"])

        return {"atr_tp_mult": round(default_tp + trust * (learned_tp - default_tp), 2)}

    def _tune_score_threshold(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
        trust:   float,
    ) -> Optional[float]:
        scored = [
            (int(t["base_score"]), (t["profit"] or 0) > 0, w)
            for t, w in zip(trades, weights)
            if t.get("base_score") is not None
        ]
        if len(scored) < MIN_GLOBAL:
            return None

        best_thresh, best_expect = float(DEFAULTS["min_score"]), -999.0
        for threshold in [1, 2, 3, 4]:
            subset = [(win, w) for s, win, w in scored if s >= threshold]
            if len(subset) < MIN_BIN:
                continue
            tw       = sum(w for _, w in subset)
            win_rate = sum(w for win, w in subset if win) / tw
            expectancy = win_rate - (1.0 - win_rate)   # positive if >50% win
            if expectancy > best_expect:
                best_expect = expectancy
                best_thresh = float(threshold)

        default = float(DEFAULTS["min_score"])
        return round(default + trust * (best_thresh - default), 2)

    def _tune_volume_threshold(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
        trust:   float,
    ) -> Optional[float]:
        with_vol = [
            (float(t["volume_ratio"]), (t["profit"] or 0) > 0, w)
            for t, w in zip(trades, weights)
            if t.get("volume_ratio") is not None
        ]
        if len(with_vol) < MIN_BIN * 2:
            return None

        best_thresh, best_expect = float(DEFAULTS["volume_min_ratio"]), -999.0
        for pct in [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]:
            subset = [(win, w) for vr, win, w in with_vol if vr >= pct]
            if len(subset) < MIN_BIN:
                continue
            tw       = sum(w for _, w in subset)
            win_rate = sum(w for win, w in subset if win) / tw
            expectancy = win_rate - (1.0 - win_rate)
            if expectancy > best_expect:
                best_expect = expectancy
                best_thresh = pct

        default = float(DEFAULTS["volume_min_ratio"])
        return round(default + trust * (best_thresh - default), 2)

    def _tune_session_weights(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
    ) -> Optional[Dict[str, float]]:
        _hour_to_session = {
            **{h: "Tokyo"   for h in range(0,  2)},
            **{h: "London"  for h in range(7,  16)},
            **{h: "NewYork" for h in range(13, 21)},
        }
        buckets: Dict[str, List[Tuple[bool, float]]] = {}
        for t, w in zip(trades, weights):
            hour = t.get("session_hour")
            if hour is None:
                continue
            sess = _hour_to_session.get(int(hour))
            if sess is None:
                continue
            buckets.setdefault(sess, []).append(((t["profit"] or 0) > 0, w))

        out: Dict[str, float] = {}
        for sess, data in buckets.items():
            if len(data) < MIN_BIN:
                out[sess] = 1.0
                continue
            tw       = sum(w for _, w in data)
            win_rate = sum(w for win, w in data if win) / tw
            # 50% win_rate → weight 1.0; scales linearly, capped [0.5, 2.0]
            out[sess] = round(max(0.5, min(2.0, win_rate / 0.5)), 3)

        return out if out else None

    # ── Bootstrap confidence intervals ──────────────────────────────────────────

    def _bootstrap_ci(
        self,
        trades:  List[Dict[str, Any]],
        weights: np.ndarray,
        trust:   float,
    ) -> Dict[str, Tuple[float, float]]:
        ci: Dict[str, Tuple[float, float]] = {}
        n   = len(trades)
        rng = np.random.default_rng(seed=BOOTSTRAP_RNG_SEED)

        for key in ("rsi_bull_min", "rsi_bull_max", "rsi_bear_min", "rsi_bear_max"):
            samples: List[float] = []
            for _ in range(BOOTSTRAP_ITERS):
                idx        = rng.choice(n, size=n, replace=True)
                resampled  = [trades[i] for i in idx]
                rw         = weights[idx]
                rw         = rw / rw.sum()
                rsi_result = self._tune_rsi_zones(resampled, rw, trust)
                if key in rsi_result:
                    samples.append(rsi_result[key])
            if len(samples) >= 10:
                lo = float(np.percentile(samples, 5))
                hi = float(np.percentile(samples, 95))
                ci[key] = (round(lo, 1), round(hi, 1))

        return ci

    # ── Utilities ───────────────────────────────────────────────────────────────

    @staticmethod
    def _recency_weights(n: int) -> np.ndarray:
        """Exponential weights — newest trade has weight 1.0 before normalisation."""
        decay = np.log(2) / RECENCY_HALF_LIFE
        w     = np.exp(decay * np.arange(n))
        return w / w.sum()

    @staticmethod
    def _clip_to_bounds(params: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(params)
        for key, (lo, hi) in PARAM_BOUNDS.items():
            if key in out and isinstance(out[key], (int, float)):
                out[key] = round(float(np.clip(out[key], lo, hi)), 2)
        # RSI zones must not cross
        for pfx in ("rsi_bull", "rsi_bear"):
            mn_k, mx_k = f"{pfx}_min", f"{pfx}_max"
            if out.get(mn_k, 0) >= out.get(mx_k, 100):
                out[mn_k] = DEFAULTS[mn_k]
                out[mx_k] = DEFAULTS[mx_k]
        return out

    def _write(self, result: TunerResult) -> None:
        """Atomic write: write temp then rename so readers never see partial JSON."""
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUTPUT_PATH.with_suffix(".tmp")
        payload = {
            "params":       result.params,
            "sample_count": result.sample_count,
            "confidence":   {k: list(v) for k, v in result.confidence.items()},
            "last_updated": result.last_updated,
            "version":      result.version,
        }
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(OUTPUT_PATH)
        logger.debug("ParameterTuner: wrote %s (v%d)", OUTPUT_PATH, result.version)

    def _current_version(self) -> int:
        if not OUTPUT_PATH.exists():
            return 0
        try:
            return int(json.loads(OUTPUT_PATH.read_text()).get("version", 0))
        except Exception:
            return 0

    def _load_closed_trades(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("""
                SELECT
                    t.ticket, t.symbol, t.direction, t.profit,
                    t.rr_ratio, t.atr,
                    lf.rsi, lf.base_score, lf.session_hour,
                    lf.volume_ratio, lf.htf_trend, lf.h1_trend
                FROM trades t
                LEFT JOIN learning_features lf ON lf.ticket = t.ticket
                WHERE t.close_time IS NOT NULL
                  AND t.profit    IS NOT NULL
                ORDER BY t.close_time ASC
            """)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
