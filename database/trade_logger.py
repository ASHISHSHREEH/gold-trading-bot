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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                signal      TEXT,
                confidence  TEXT,
                price       REAL,
                atr         REAL,
                trend       TEXT,
                rsi         REAL,
                macd        TEXT,
                bb_position TEXT,
                score       INTEGER,
                action      TEXT,
                session_id  INTEGER REFERENCES sessions(id)
            );
        """)
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
            f"net P&L={stats.get('total_profit', 0):.2f}"
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
                   macd, bb_position, score, action, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    self._session_id,
                ),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"log_signal failed: {e}")

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
