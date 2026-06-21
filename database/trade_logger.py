"""
TradeLogger — SQLite analytics store for post-trade analysis.

This sits OUTSIDE the execution path.  MT5 is the source of truth for
open positions and account state.  This database records what happened
so we can run performance analytics, tune parameters, and build reports.

Tables:
    trades   — every executed trade (open + close)
    signals  — every generated signal including NEUTRAL / BLOCKED
    sessions — per-run summary (start/end balance, win rate, etc.)
"""
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TradeLogger:

    def __init__(self, db_path: str = "data/trading_mt5.db"):
        Path(os.path.dirname(db_path)).mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
        self._create_tables()
        self._migrate_schema()
        self._session_id: Optional[int] = None
        logger.info(f"TradeLogger initialised: {db_path}")

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time      DATETIME NOT NULL,
                end_time        DATETIME,
                start_balance   REAL     NOT NULL,
                end_balance     REAL,
                total_trades    INTEGER  DEFAULT 0,
                winning_trades  INTEGER  DEFAULT 0,
                net_profit      REAL     DEFAULT 0,
                max_drawdown    REAL     DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket      INTEGER UNIQUE NOT NULL,
                symbol      TEXT    NOT NULL,
                direction   TEXT    NOT NULL,
                open_time   DATETIME,
                close_time  DATETIME,
                entry_price REAL,
                exit_price  REAL,
                volume      REAL,
                stop_loss   REAL,
                take_profit REAL,
                profit      REAL,
                atr         REAL,
                rr_ratio    REAL,
                exit_reason TEXT,
                session_id  INTEGER REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS signals (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP,
                signal         TEXT,
                confidence     TEXT,
                price          REAL,
                atr            REAL,
                trend          TEXT,
                rsi            REAL,
                macd           TEXT,
                bb_position    TEXT,
                score          INTEGER,
                action         TEXT,
                candle_pattern TEXT,
                session_id     INTEGER REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS learning_features (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket         INTEGER UNIQUE,
                logged_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                symbol         TEXT,
                direction      TEXT,
                -- Multi-timeframe features at entry
                htf_trend      TEXT,
                h1_trend       TEXT,
                m15_trend      TEXT,
                m1_direction   TEXT,
                -- Indicator values at entry
                rsi            REAL,
                macd_signal    TEXT,
                bb_position    TEXT,
                atr            REAL,
                spread         REAL,
                volume_ratio   REAL,
                -- Candlestick pattern at entry (CNN training label)
                candle_pattern TEXT,
                -- Scoring
                base_score     INTEGER,
                session_hour   INTEGER,
                -- AI layer outputs at entry
                ml_score       REAL,
                rl_vote        TEXT,
                ai_confidence  REAL,
                ai_decision    TEXT,
                -- Outcome (filled when trade closes)
                outcome        INTEGER,   -- 1=WIN, 0=LOSS, NULL=open
                rr_achieved    REAL,
                hold_minutes   REAL,
                FOREIGN KEY(ticket) REFERENCES trades(ticket)
            );
        """)
        self.conn.commit()

    def _migrate_schema(self):
        """Add columns introduced after the initial schema (safe on existing DBs)."""
        migrations = [
            ("signals",          "candle_pattern TEXT"),
            ("learning_features", "candle_pattern TEXT"),
        ]
        for table, column_def in migrations:
            col_name = column_def.split()[0]
            existing = {
                row[1]
                for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if col_name not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
                logger.info("DB migration: added %s.%s", table, col_name)
        self.conn.commit()

    # ── Session Management ─────────────────────────────────────────────────────

    def start_session(self, start_balance: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (start_time, start_balance) VALUES (?, ?)",
            (datetime.now(), start_balance),
        )
        self.conn.commit()
        self._session_id = cur.lastrowid
        logger.info(f"Session {self._session_id} started | balance={start_balance:.2f}")
        return self._session_id

    def end_session(self, end_balance: float):
        if self._session_id is None:
            return
        stats = self.get_statistics()
        self.conn.execute(
            """
            UPDATE sessions
            SET end_time=?, end_balance=?, total_trades=?,
                winning_trades=?, net_profit=?
            WHERE id=?
            """,
            (
                datetime.now(),
                end_balance,
                stats.get("total_trades", 0),
                stats.get("winning_trades", 0),
                stats.get("total_profit") or 0.0,
                self._session_id,
            ),
        )
        self.conn.commit()
        logger.info(
            f"Session {self._session_id} closed | "
            f"net P&L={stats.get('total_profit') or 0:.2f}"
        )

    # ── Trade Recording ────────────────────────────────────────────────────────

    def log_trade_open(self, execution: Dict[str, Any]):
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO trades
                  (ticket, symbol, direction, open_time, entry_price,
                   volume, stop_loss, take_profit, atr, rr_ratio, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution.get("ticket"),
                    execution.get("symbol"),
                    execution.get("direction"),
                    datetime.now(),
                    execution.get("entry_price"),
                    execution.get("volume"),
                    execution.get("stop_loss"),
                    execution.get("take_profit"),
                    execution.get("atr"),
                    execution.get("rr_ratio"),
                    self._session_id,
                ),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"log_trade_open failed: {e}")

    def log_trade_close(
        self,
        ticket: int,
        exit_price: float,
        profit: float,
        reason: str = "",
    ):
        try:
            self.conn.execute(
                """
                UPDATE trades
                SET close_time=?, exit_price=?, profit=?, exit_reason=?
                WHERE ticket=?
                """,
                (datetime.now(), exit_price, profit, reason, ticket),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"log_trade_close failed: {e}")

    def get_zombie_tickets(self, open_tickets: list) -> list:
        """Return ticket IDs that are unclosed in the DB but no longer open in MT5."""
        try:
            cur = self.conn.execute(
                "SELECT ticket FROM trades WHERE close_time IS NULL"
            )
            unclosed = [row[0] for row in cur.fetchall()]
            return [t for t in unclosed if t not in open_tickets]
        except sqlite3.Error as e:
            logger.error(f"get_zombie_tickets failed: {e}")
            return []

    def close_zombie_trades(
        self,
        open_tickets: list,
        ticket_exit_data: dict = None,
    ) -> int:
        """
        Mark DB trades as closed if they are no longer open in MT5.
        Called on startup to clean up records from crashed/interrupted sessions.

        ticket_exit_data: optional dict mapping ticket → deal dict with keys
            exit_price, profit, close_time_epoch.  When present, real values are
            recorded so ML training has valid labels.  Tickets without an entry
            fall back to NULL exit_price/profit (flagged for manual review).

        Returns number of records fixed.
        """
        if ticket_exit_data is None:
            ticket_exit_data = {}
        try:
            zombies = self.get_zombie_tickets(open_tickets)
            for ticket in zombies:
                deal = ticket_exit_data.get(ticket)
                if deal:
                    close_dt = datetime.fromtimestamp(deal["close_time_epoch"])
                    self.conn.execute(
                        """UPDATE trades
                           SET close_time=?, exit_price=?, profit=?,
                               exit_reason='zombie_cleanup'
                           WHERE ticket=? AND close_time IS NULL""",
                        (close_dt, deal["exit_price"], deal["profit"], ticket),
                    )
                else:
                    self.conn.execute(
                        """UPDATE trades
                           SET close_time=?, exit_reason='zombie_cleanup_no_data'
                           WHERE ticket=? AND close_time IS NULL""",
                        (datetime.now(), ticket),
                    )
            self.conn.commit()
            if zombies:
                resolved = [t for t in zombies if t in ticket_exit_data]
                missing  = [t for t in zombies if t not in ticket_exit_data]
                logger.info(
                    "Cleaned %d zombie trade(s): %d with MT5 data %s, "
                    "%d without %s",
                    len(zombies), len(resolved), resolved, len(missing), missing,
                )
            return len(zombies)
        except sqlite3.Error as e:
            logger.error(f"close_zombie_trades failed: {e}")
            return 0

    # ── Signal Recording ───────────────────────────────────────────────────────

    def log_signal(
        self,
        signal_data: Dict[str, Any],
        price: float,
        atr: float,
        action: str,
    ):
        """
        Record every signal evaluation — including NEUTRAL and BLOCKED signals.
        This is the audit trail used to tune indicator parameters.
        """
        try:
            self.conn.execute(
                """
                INSERT INTO signals
                  (signal, confidence, price, atr, trend, rsi,
                   macd, bb_position, score, action, candle_pattern, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_data.get("signal"),
                    signal_data.get("confidence"),
                    price,
                    atr,
                    signal_data.get("trend"),
                    signal_data.get("rsi"),
                    signal_data.get("macd"),
                    signal_data.get("bb"),
                    signal_data.get("score", 0),
                    action,
                    signal_data.get("candle_pattern"),
                    self._session_id,
                ),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"log_signal failed: {e}")

    # ── Learning Features ──────────────────────────────────────────────────────

    def log_learning_features(self, ticket: int, features: Dict[str, Any]) -> None:
        """
        Store ML features at the moment a trade is opened.
        Called immediately after log_trade_open so the AI has a training row.
        """
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_features
                  (ticket, symbol, direction,
                   htf_trend, h1_trend, m15_trend, m1_direction,
                   rsi, macd_signal, bb_position, atr, spread, volume_ratio,
                   candle_pattern,
                   base_score, session_hour,
                   ml_score, rl_vote, ai_confidence, ai_decision)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ticket,
                    features.get("symbol"),
                    features.get("direction"),
                    features.get("htf_trend"),
                    features.get("h1_trend"),
                    features.get("m15_trend"),
                    features.get("m1_direction"),
                    features.get("rsi"),
                    features.get("macd_signal"),
                    features.get("bb_position"),
                    features.get("atr"),
                    features.get("spread"),
                    features.get("volume_ratio"),
                    features.get("candle_pattern"),
                    features.get("base_score"),
                    features.get("session_hour"),
                    features.get("ml_score"),
                    features.get("rl_vote"),
                    features.get("ai_confidence"),
                    features.get("ai_decision"),
                ),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error("log_learning_features failed: %s", e)

    def update_learning_outcome(
        self,
        ticket:       int,
        profit:       float,
        entry_price:  float,
        exit_price:   float,
        open_time_dt: Optional[Any] = None,
        close_time_dt: Optional[Any] = None,
    ) -> None:
        """
        Fill in outcome columns when a position closes.
        win=1/loss=0, realised RR, and hold duration in minutes.
        """
        try:
            outcome = 1 if profit > 0 else 0

            # Approximate realised RR from stored initial SL
            cur = self.conn.execute(
                "SELECT stop_loss FROM trades WHERE ticket=?", (ticket,)
            )
            row = cur.fetchone()
            rr_achieved: Optional[float] = None
            if row and row["stop_loss"] is not None and row["stop_loss"] != entry_price:
                risk = abs(entry_price - row["stop_loss"])
                if risk > 0:
                    rr_achieved = round(abs(exit_price - entry_price) / risk, 3)

            hold_minutes: Optional[float] = None
            if open_time_dt and close_time_dt:
                try:
                    delta = close_time_dt - open_time_dt
                    hold_minutes = round(delta.total_seconds() / 60.0, 1)
                except Exception:
                    pass

            self.conn.execute(
                """
                UPDATE learning_features
                SET outcome=?, rr_achieved=?, hold_minutes=?
                WHERE ticket=?
                """,
                (outcome, rr_achieved, hold_minutes, ticket),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error("update_learning_outcome failed: %s", e)

    def get_closed_trade_count(self) -> int:
        """Return count of fully closed trades (used by AI retraining scheduler)."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM trades WHERE close_time IS NOT NULL AND profit IS NOT NULL"
        )
        return int((cur.fetchone() or [0])[0])

    def get_open_tickets_without_close(self) -> List[int]:
        """Return ticket IDs of trades that are open in the DB (no close_time yet)."""
        cur = self.conn.execute(
            "SELECT ticket FROM trades WHERE close_time IS NULL"
        )
        return [row[0] for row in cur.fetchall()]

    # ── Analytics ──────────────────────────────────────────────────────────────

    def get_statistics(self) -> Dict[str, Any]:
        cur = self.conn.execute(
            """
            SELECT
                COUNT(*)                                        AS total_trades,
                SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END)    AS winning_trades,
                SUM(profit)                                     AS total_profit,
                AVG(CASE WHEN profit > 0 THEN profit END)       AS avg_win,
                AVG(CASE WHEN profit < 0 THEN profit END)       AS avg_loss,
                MAX(profit)                                     AS best_trade,
                MIN(profit)                                     AS worst_trade
            FROM trades
            WHERE close_time IS NOT NULL
            """
        )
        row   = cur.fetchone()
        stats = dict(row) if row else {}

        total = stats.get("total_trades") or 0
        wins  = stats.get("winning_trades") or 0
        stats["win_rate"] = (wins / total * 100) if total > 0 else 0.0

        gross_win  = abs(stats.get("avg_win")  or 0) * wins
        gross_loss = abs(stats.get("avg_loss") or 0) * (total - wins)
        stats["profit_factor"] = (gross_win / gross_loss) if gross_loss > 0 else 0.0

        return stats

    def get_recent_trades(self, limit: int = 5) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM trades WHERE close_time IS NOT NULL "
            "ORDER BY close_time DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("TradeLogger closed.")
