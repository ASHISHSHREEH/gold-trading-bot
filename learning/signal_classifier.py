"""
SignalClassifier — RandomForest pipeline trained on the bot's own trade outcomes.

Architecture:
  • Features: RSI, MACD, BB, all trend timeframes, ATR, spread, volume, session, score
  • Target: binary WIN=1 / LOSS=0
  • Pipeline: ColumnTransformer(OrdinalEncoder + StandardScaler) → RandomForest
  • Calibrated probabilities via Platt scaling (CalibratedClassifierCV)
  • Anti-overfit: max_depth=6, min_samples_leaf=5, class_weight='balanced'
  • Drift detection: Population Stability Index on held-out feature distributions
  • Model versioning: learning/models/classifier_v{N}.pkl  (keeps last 3)
  • Falls back to win_probability=0.5 if < MIN_TRAIN_SAMPLES trades or sklearn missing
  • Never overrides base strategy — acts as probabilistic confirmation only
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR        = Path("learning/models")
MIN_TRAIN_SAMPLES = 50
RETRAIN_EVERY_N   = 50    # retrain after N additional closed trades
PSI_THRESHOLD     = 0.20  # Population Stability Index — flag drift above this
CV_FOLDS          = 5
MAX_DEPTH         = 6
MIN_SAMPLES_LEAF  = 5
N_ESTIMATORS      = 200

_INACTIVE_RESULT: Dict[str, Any] = {
    "win_probability":   0.5,
    "ml_score":          0.5,
    "confidence":        "INACTIVE",
    "feature_importance": {},
    "active":            False,
    "train_count":       0,
}

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OrdinalEncoder, StandardScaler
    _SK = True
except ImportError:
    _SK = False
    logger.warning("scikit-learn not installed — SignalClassifier disabled (pip install scikit-learn).")


class SignalClassifier:
    """
    Probabilistic signal filter trained on actual closed trade outcomes.

    Predicts the probability that a BUY/SELL signal will be a winner given
    the current market features.  The output influences but never overrides
    the rule-based strategy score.
    """

    # ── Feature schema ──────────────────────────────────────────────────────────
    # Categorical columns (positional index 0–5 in feature matrix)
    _CAT = ["macd_signal", "bb_position", "htf_trend", "h1_trend", "m15_trend", "m1_direction"]
    # Numeric columns (index 6–11)
    _NUM = ["rsi", "atr", "spread", "volume_ratio", "base_score", "session_hour"]
    FEATURE_NAMES = _CAT + _NUM

    def __init__(self, db_path: str = "data/trading_mt5.db") -> None:
        self.db_path              = db_path
        self.pipeline: Optional[object] = None   # sklearn Pipeline
        self._version             = 0
        self._train_count         = 0
        self._cv_auc              = 0.0
        self._fingerprint         = ""
        self._feature_importance: Dict[str, float] = {}
        self._ref_distributions: Optional[Dict[str, np.ndarray]] = None

        if not _SK:
            return

        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_latest_model()
        logger.info(
            "SignalClassifier ready | version=%d | trained_on=%d | CV-AUC=%.3f",
            self._version, self._train_count, self._cv_auc,
        )

    # ── Public API ──────────────────────────────────────────────────────────────

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return win probability for the current signal's feature set.

        Args:
            features: dict with keys matching FEATURE_NAMES (missing keys → safe defaults)

        Returns:
            {"win_probability": float, "ml_score": float,
             "confidence": str, "feature_importance": dict, "active": bool}
        """
        if not _SK or self.pipeline is None:
            return dict(_INACTIVE_RESULT)
        if self._train_count < MIN_TRAIN_SAMPLES:
            return {**_INACTIVE_RESULT, "confidence": "INSUFFICIENT_DATA", "train_count": self._train_count}

        try:
            X    = self._to_matrix([features])
            prob = float(self.pipeline.predict_proba(X)[0][1])
            conf = "HIGH" if prob >= 0.65 else ("MODERATE" if prob >= 0.50 else "LOW")
            return {
                "win_probability":   round(prob, 4),
                "ml_score":          round(prob, 4),
                "confidence":        conf,
                "feature_importance": self._feature_importance,
                "active":            True,
                "train_count":       self._train_count,
            }
        except Exception as exc:
            logger.error("SignalClassifier.predict error: %s", exc, exc_info=True)
            return dict(_INACTIVE_RESULT)

    def train(self) -> bool:
        """
        Load all closed trades with ML features from SQLite and retrain.
        Skips silently if data hasn't changed or is insufficient.
        Returns True on successful train.
        """
        if not _SK:
            return False

        rows = self._load_rows()
        if len(rows) < MIN_TRAIN_SAMPLES:
            logger.info("SignalClassifier.train: %d/%d trades — skipping.", len(rows), MIN_TRAIN_SAMPLES)
            return False

        fp = self._fingerprint_rows(rows)
        if fp == self._fingerprint:
            logger.debug("SignalClassifier.train: data unchanged — skipping retrain.")
            return True

        X, y = self._make_dataset(rows)
        pos, neg = int(y.sum()), len(y) - int(y.sum())
        logger.info("SignalClassifier.train: %d samples (win=%d, loss=%d)", len(X), pos, neg)

        pipeline = self._build_pipeline()
        n_splits = min(CV_FOLDS, max(2, pos))   # can't have more folds than positive samples
        skf      = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        try:
            cv_scores     = cross_val_score(pipeline, X, y, cv=skf, scoring="roc_auc", n_jobs=-1)
            self._cv_auc  = float(cv_scores.mean())
            logger.info("SignalClassifier: CV ROC-AUC = %.3f ± %.3f", cv_scores.mean(), cv_scores.std())
        except Exception as exc:
            logger.warning("SignalClassifier: cross-val failed — %s", exc)
            self._cv_auc = 0.0

        pipeline.fit(X, y)
        self.pipeline       = pipeline
        self._train_count   = len(rows)
        self._fingerprint   = fp
        self._version      += 1
        self._extract_importances(pipeline)
        self._update_reference_distributions(X)
        self._save(pipeline)
        logger.info(
            "SignalClassifier: trained model v%d | %d trades | AUC=%.3f",
            self._version, self._train_count, self._cv_auc,
        )
        return True

    def should_retrain(self, closed_trade_count: int) -> bool:
        if self._train_count == 0 and closed_trade_count >= MIN_TRAIN_SAMPLES:
            return True
        return (closed_trade_count - self._train_count) >= RETRAIN_EVERY_N

    def drift_score(self, recent_features: List[Dict[str, Any]]) -> float:
        """
        Compute PSI between training distribution and recent features.
        PSI > 0.2 suggests significant distribution shift (model may need retrain).
        Returns 0.0 if reference distributions not set yet.
        """
        if self._ref_distributions is None or len(recent_features) < 10:
            return 0.0
        try:
            X_recent = self._to_matrix(recent_features)
            # Compare numeric columns only (indices 6–11)
            psi_scores = []
            for col_idx in range(len(self._CAT), len(self.FEATURE_NAMES)):
                ref_col    = self._ref_distributions.get(str(col_idx))
                recent_col = X_recent[:, col_idx].astype(float)
                if ref_col is None or len(ref_col) < 5:
                    continue
                psi = self._psi(ref_col, recent_col)
                psi_scores.append(psi)
            return float(np.mean(psi_scores)) if psi_scores else 0.0
        except Exception as exc:
            logger.debug("drift_score error: %s", exc)
            return 0.0

    # ── Feature engineering ─────────────────────────────────────────────────────

    def _to_matrix(self, rows: List[Dict[str, Any]]) -> np.ndarray:
        records = []
        for r in rows:
            records.append([
                r.get("macd_signal")   or "NEUTRAL",
                r.get("bb_position")   or "MIDDLE",
                r.get("htf_trend")     or "NEUTRAL",
                r.get("h1_trend")      or "NEUTRAL",
                r.get("m15_trend")     or "NEUTRAL",
                r.get("m1_direction")  or "NEUTRAL",
                float(r.get("rsi")          or 50.0),
                float(r.get("atr")          or 0.0),
                float(r.get("spread")       or 0.0),
                float(r.get("volume_ratio") or 1.0),
                float(r.get("base_score")   or 0.0),
                float(r.get("session_hour") or 12.0),
            ])
        return np.array(records, dtype=object)

    def _make_dataset(self, rows: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        X = self._to_matrix(rows)
        y = np.array([1 if (r.get("profit") or 0) > 0 else 0 for r in rows], dtype=int)
        return X, y

    def _build_pipeline(self) -> "Pipeline":
        n_cat = len(self._CAT)
        n_tot = len(self.FEATURE_NAMES)
        cat_idx = list(range(n_cat))
        num_idx = list(range(n_cat, n_tot))

        prep = ColumnTransformer([
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cat_idx),
            ("num", StandardScaler(), num_idx),
        ])
        rf = RandomForestClassifier(
            n_estimators     = N_ESTIMATORS,
            max_depth        = MAX_DEPTH,
            min_samples_leaf = MIN_SAMPLES_LEAF,
            class_weight     = "balanced",
            n_jobs           = -1,
            random_state     = 42,
        )
        cal = CalibratedClassifierCV(rf, cv=3, method="sigmoid")
        return Pipeline([("prep", prep), ("clf", cal)])

    # ── Model persistence ────────────────────────────────────────────────────────

    def _save(self, pipeline: "Pipeline") -> None:
        path = MODELS_DIR / f"classifier_v{self._version}.pkl"
        meta = {
            "version":            self._version,
            "cv_auc":             self._cv_auc,
            "train_count":        self._train_count,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
            "feature_importance": self._feature_importance,
            "fingerprint":        self._fingerprint,
        }
        with open(path, "wb") as fh:
            pickle.dump({"pipeline": pipeline, "meta": meta,
                         "ref_distributions": self._ref_distributions}, fh, protocol=4)
        self._prune_old_models(keep=3)
        logger.debug("SignalClassifier: saved %s", path)

    def _load_latest_model(self) -> None:
        models = sorted(MODELS_DIR.glob("classifier_v*.pkl"))
        if not models:
            return
        path = models[-1]
        try:
            with open(path, "rb") as fh:
                data = pickle.load(fh)
            self.pipeline                  = data["pipeline"]
            meta                           = data.get("meta", {})
            self._version                  = int(meta.get("version", 0))
            self._cv_auc                   = float(meta.get("cv_auc", 0.0))
            self._train_count              = int(meta.get("train_count", 0))
            self._feature_importance       = meta.get("feature_importance", {})
            self._fingerprint              = meta.get("fingerprint", "")
            self._ref_distributions        = data.get("ref_distributions")
            logger.info("SignalClassifier: loaded model v%d from %s", self._version, path)
        except Exception as exc:
            logger.warning("SignalClassifier: failed to load %s — %s", path, exc)
            self.pipeline = None

    def _prune_old_models(self, keep: int = 3) -> None:
        for path in sorted(MODELS_DIR.glob("classifier_v*.pkl"))[:-keep]:
            try:
                path.unlink()
            except OSError:
                pass

    def _extract_importances(self, pipeline: "Pipeline") -> None:
        try:
            cal          = pipeline.named_steps["clf"]
            importances  = np.mean(
                [
                    (cc.estimator.feature_importances_
                     if hasattr(cc, "estimator")
                     else getattr(cc, "feature_importances_", np.zeros(len(self.FEATURE_NAMES))))
                    for cc in cal.calibrated_classifiers_
                ],
                axis=0,
            )
            if len(importances) == len(self.FEATURE_NAMES):
                self._feature_importance = {
                    n: round(float(v), 4)
                    for n, v in zip(self.FEATURE_NAMES, importances)
                }
        except Exception as exc:
            logger.debug("_extract_importances: %s", exc)

    def _update_reference_distributions(self, X: np.ndarray) -> None:
        """Store numeric column distributions for future PSI drift checks."""
        n_cat = len(self._CAT)
        self._ref_distributions = {
            str(i): X[:, i].astype(float)
            for i in range(n_cat, len(self.FEATURE_NAMES))
        }

    # ── Drift detection (PSI) ────────────────────────────────────────────────────

    @staticmethod
    def _psi(expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
        """Population Stability Index.  <0.1 = stable, 0.1-0.2 = monitor, >0.2 = drift."""
        eps   = 1e-4
        bins  = np.percentile(expected, np.linspace(0, 100, buckets + 1))
        bins  = np.unique(bins)
        if len(bins) < 2:
            return 0.0
        e_cnt = np.histogram(expected, bins=bins)[0] + eps
        a_cnt = np.histogram(actual,   bins=bins)[0] + eps
        e_pct = e_cnt / e_cnt.sum()
        a_pct = a_cnt / a_cnt.sum()
        return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))

    # ── Database ─────────────────────────────────────────────────────────────────

    def _load_rows(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("""
                SELECT
                    t.profit,
                    lf.rsi, lf.macd_signal, lf.bb_position,
                    lf.htf_trend, lf.h1_trend, lf.m15_trend, lf.m1_direction,
                    lf.atr, lf.spread, lf.volume_ratio,
                    lf.base_score, lf.session_hour
                FROM trades t
                INNER JOIN learning_features lf ON lf.ticket = t.ticket
                WHERE t.close_time IS NOT NULL
                  AND t.profit     IS NOT NULL
                  AND lf.rsi       IS NOT NULL
                ORDER BY t.close_time ASC
            """)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _fingerprint_rows(rows: List[Dict[str, Any]]) -> str:
        sentinel = [(r.get("profit", 0), r.get("rsi", 0)) for r in rows[-15:]]
        return hashlib.md5(str(sentinel).encode()).hexdigest()
