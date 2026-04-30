"""
Trade Logger — SQLite analytics store.
MT5 executes and manages all trades.  This module exists solely to
record every execution for performance analysis, backtesting, and reporting.

Schema:
  trades       — every closed trade imported from MT5 deal history
  signals      — every signal generated (including NEUTRAL) for strategy audit
  sessions     — per-session summary (start/end balance, trade count, etc.)
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class TradeLogger:

    def __init__(self, db_path: str = "data/trading_log.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent writes
        self._create_tables()
        logger.info(f"TradeLogger connected: {db_path}")

    # ── Schema ──────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        cur = self._conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket        INTEGER UNIQUE NOT NULL,
                symbol        TEXT    NOT NULL,
                direction     TEXT    NOT NULL,    -- LONG / SHORT
                open_time     DATETIME NOT NULL,
                close_time    DATETIME,
                entry_price   REAL    NOT NULL,
                exit_price    REAL,
                volume        REAL    NOT NULL,
                stop_loss     REAL,
                take_profit   REAL,
                profit        REAL,
                swap          REAL    DEFAULT 0,
                commission    REAL    DEFAULT 0,
                exit_reason   TEXT,
                confidence    TEXT,
                signal_notes  TEXT,
                logged_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     DATETIME NOT NULL,
                symbol        TEXT    NOT NULL,
                signal        TEXT    NOT NULL,    -- BUY / SELL / NEUTRAL
                confidence    TEXT,
                trend         TEXT,
                rsi           REAL,
                macd_signal   TEXT,
                bb_position   TEXT,
                atr           REAL,
                price         REAL,
                action_taken  TEXT,               -- EXECUTED / SKIPPED / BLOCKED
                block_reason  TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time      DATETIME NOT NULL,
                end_time        DATETIME,
                start_balance   REAL,
                end_balance     REAL,
                net_pnl         REAL,
                pnl_pct         REAL,
                total_signals   INTEGER  DEFAULT 0,
                trades_taken    INTEGER  DEFAULT 0,
                wins            INTEGER  DEFAULT 0,
                losses          INTEGER  DEFAULT 0
            );
        """)
        self._conn.commit()

    # ── Trade Logging ───────────────────────────────────────────────────────

    def log_trade_open(self, execution: Dict[str, Any]) -> None:
        """Log a newly opened MT5 trade."""
        try:
            self._conn.execute("""
                INSERT OR IGNORE INTO trades
                    (ticket, symbol, direction, open_time,
                     entry_price, volume, stop_loss, take_profit,
                     confidence, signal_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution["ticket"],
                execution["symbol"],
                execution["direction"],
                datetime.utcnow(),
                execution["entry_price"],
                execution["volume"],
                execution.get("stop_loss"),
                execution.get("take_profit"),
                execution.get("confidence"),
                execution.get("comment"),
            ))
            self._conn.commit()
            logger.debug(f"Logged trade open: ticket={execution['ticket']}")
        except sqlite3.Error as e:
            logger.error(f"Failed to log trade open: {e}")

    def log_trade_close(
        self,
        ticket: int,
        exit_price: float,
        profit: float,
        swap: float = 0.0,
        commission: float = 0.0,
        exit_reason: str = "MT5",
    ) -> None:
        """Update the trade record when MT5 closes a position."""
        try:
            self._conn.execute("""
                UPDATE trades
                SET close_time  = ?,
                    exit_price  = ?,
                    profit      = ?,
                    swap        = ?,
                    commission  = ?,
                    exit_reason = ?
                WHERE ticket = ?
            """, (
                datetime.utcnow(),
                exit_price, profit, swap, commission,
                exit_reason, ticket,
            ))
            self._conn.commit()
            logger.debug(f"Logged trade close: ticket={ticket} profit={profit:.2f}")
        except sqlite3.Error as e:
            logger.error(f"Failed to log trade close: {e}")

    # ── Signal Logging ──────────────────────────────────────────────────────

    def log_signal(
        self,
        signal_data: Dict[str, Any],
        price: float,
        atr: float,
        action_taken: str,
        block_reason: str = "",
    ) -> None:
        """
        Log every signal (including NEUTRAL and BLOCKED) for strategy audit.
        Essential for post-run analysis — you can't improve what you don't track.
        """
        try:
            rsi_analysis  = signal_data.get("entry_analysis", {}).get("rsi_analysis", {})
            macd_analysis = signal_data.get("entry_analysis", {}).get("macd_analysis", {})
            bb_analysis   = signal_data.get("entry_analysis", {}).get("bb_analysis", {})

            self._conn.execute("""
                INSERT INTO signals
                    (timestamp, symbol, signal, confidence, trend,
                     rsi, macd_signal, bb_position, atr, price,
                     action_taken, block_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow(),
                signal_data.get("symbol", "XAUUSD"),
                signal_data.get("signal", "NEUTRAL"),
                signal_data.get("confidence"),
                str(signal_data.get("trend", {}).get("trend", "")),
                rsi_analysis.get("rsi"),
                macd_analysis.get("signal"),
                bb_analysis.get("position"),
                atr,
                price,
                action_taken,
                block_reason,
            ))
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to log signal: {e}")

    # ── Session Logging ─────────────────────────────────────────────────────

    def start_session(self, balance: float) -> int:
        """Create a new session record. Returns session ID."""
        try:
            cur = self._conn.execute(
                "INSERT INTO sessions (start_time, start_balance) VALUES (?, ?)",
                (datetime.utcnow(), balance)
            )
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Failed to start session: {e}")
            return -1

    def end_session(self, session_id: int, end_balance: float) -> None:
        """Update session record at bot shutdown."""
        try:
            cur = self._conn.execute(
                "SELECT start_balance, total_signals, trades_taken, wins, losses "
                "FROM sessions WHERE id = ?",
                (session_id,)
            )
            row = cur.fetchone()
            if not row:
                return

            start_balance = row["start_balance"] or end_balance
            net_pnl = end_balance - start_balance
            pnl_pct = (net_pnl / start_balance * 100) if start_balance > 0 else 0.0

            self._conn.execute("""
                UPDATE sessions
                SET end_time    = ?,
                    end_balance = ?,
                    net_pnl     = ?,
                    pnl_pct     = ?
                WHERE id = ?
            """, (datetime.utcnow(), end_balance, net_pnl, pnl_pct, session_id))
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to end session: {e}")

    def increment_session_counts(
        self,
        session_id: int,
        signal: bool = False,
        trade: bool = False,
        win: bool = False,
        loss: bool = False,
    ) -> None:
        try:
            updates = []
            if signal: updates.append("total_signals = total_signals + 1")
            if trade:  updates.append("trades_taken  = trades_taken  + 1")
            if win:    updates.append("wins          = wins          + 1")
            if loss:   updates.append("losses        = losses        + 1")
            if not updates:
                return
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
                (session_id,)
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to increment session counts: {e}")

    # ── Analytics Queries ───────────────────────────────────────────────────

    def get_statistics(self) -> Dict[str, Any]:
        """Aggregate performance metrics across all logged trades."""
        try:
            cur = self._conn.execute("""
                SELECT
                    COUNT(*)                                     AS total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) AS losses,
                    SUM(profit)                                  AS total_profit,
                    AVG(profit)                                  AS avg_profit,
                    MAX(profit)                                  AS best_trade,
                    MIN(profit)                                  AS worst_trade,
                    AVG(CASE WHEN profit > 0 THEN profit END)   AS avg_win,
                    AVG(CASE WHEN profit < 0 THEN profit END)   AS avg_loss
                FROM trades
                WHERE close_time IS NOT NULL
            """)
            row = dict(cur.fetchone())

            total = row["total_trades"] or 0
            row["win_rate"]      = (row["wins"] / total * 100) if total > 0 else 0.0
            row["profit_factor"] = 0.0

            if row["avg_loss"] and row["avg_loss"] != 0:
                row["profit_factor"] = abs(
                    (row["avg_win"] or 0) / row["avg_loss"]
                )

            return row
        except sqlite3.Error as e:
            logger.error(f"get_statistics failed: {e}")
            return {}

    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            cur = self._conn.execute(
                "SELECT * FROM trades WHERE close_time IS NOT NULL "
                "ORDER BY close_time DESC LIMIT ?",
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"get_recent_trades failed: {e}")
            return []

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            logger.info("TradeLogger closed.")
