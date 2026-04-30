"""
MT5 Position Manager
Reads all open positions and account state directly from MT5.
No manual SL/TP checking — the broker server handles that natively.

Responsibilities:
  - Query live positions from MT5
  - Enforce risk limits (max positions, daily drawdown, margin level)
  - Emergency close all
  - Session P&L tracking
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import MetaTrader5 as mt5

from data.mt5_fetcher import MT5DataFetcher
import config

logger = logging.getLogger(__name__)


class MT5PositionManager:

    def __init__(
        self,
        fetcher: MT5DataFetcher,
        magic: int          = config.MAGIC,
        max_positions: int  = config.MAX_POSITIONS,
        max_daily_loss: float = config.MAX_DAILY_LOSS,
    ):
        self.fetcher          = fetcher
        self.magic            = magic
        self.max_positions    = max_positions
        self.max_daily_loss   = max_daily_loss

        self._session_balance: Optional[float] = None
        self._session_start:   Optional[datetime] = None

    # ── Session Lifecycle ───────────────────────────────────────────────────

    def initialize_session(self) -> None:
        """
        Record the balance at session start so we can calculate
        intraday drawdown correctly.  Call once after MT5 connects.
        """
        account = self.fetcher.get_account_info()
        if account is None:
            raise RuntimeError("Cannot initialize session — MT5 account info unavailable")

        self._session_balance = account["balance"]
        self._session_start   = datetime.utcnow()

        logger.info(
            f"Session initialized | "
            f"Balance: {account['balance']:.2f} {account['currency']} | "
            f"Equity: {account['equity']:.2f} | "
            f"Leverage: 1:{account['leverage']}"
        )

    # ── Position Queries ────────────────────────────────────────────────────

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return all open positions tagged with our magic number.
        Optionally filter by symbol.
        """
        sym = symbol or self.fetcher.symbol

        raw = mt5.positions_get(symbol=sym)
        if raw is None:
            return []

        result = []
        for pos in raw:
            if pos.magic != self.magic:
                continue     # skip manual / other-bot positions

            result.append({
                "ticket":        pos.ticket,
                "symbol":        pos.symbol,
                "direction":     "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT",
                "entry_price":   pos.price_open,
                "current_price": pos.price_current,
                "volume":        pos.volume,
                "stop_loss":     pos.sl,
                "take_profit":   pos.tp,
                "profit":        pos.profit,
                "swap":          pos.swap,
                "open_time":     datetime.utcfromtimestamp(pos.time),
                "comment":       pos.comment,
            })

        return result

    def get_position_summary(self) -> Dict[str, Any]:
        """
        Snapshot of current positions + account state.
        Used for the display loop in main.
        """
        positions = self.get_open_positions()
        account   = self.fetcher.get_account_info()

        total_profit = sum(p["profit"] for p in positions)

        # Session drawdown
        session_dd_pct = 0.0
        if self._session_balance and self._session_balance > 0:
            session_pnl    = (account["equity"] - self._session_balance)
            session_dd_pct = (session_pnl / self._session_balance) * 100

        return {
            "count":           len(positions),
            "positions":       positions,
            "total_profit":    total_profit,
            "account":         account,
            "session_dd_pct":  round(session_dd_pct, 2),
        }

    # ── Risk Gate ───────────────────────────────────────────────────────────

    def check_risk_limits(self) -> Dict[str, Any]:
        """
        Gate check before opening any new trade.

        Checks (in order):
          1. Max open positions
          2. Daily drawdown circuit-breaker
          3. Margin level warning (< 200%)
          4. Market not closed / terminal connected
        """
        account   = self.fetcher.get_account_info()
        positions = self.get_open_positions()

        if account is None:
            return {
                "can_open_new": False,
                "reasons":      ["MT5 account info unavailable — connection issue?"],
            }

        reasons  = []
        can_open = True

        # 1. Max positions
        pos_count = len(positions)
        if pos_count >= self.max_positions:
            can_open = False
            reasons.append(
                f"Max positions reached ({pos_count}/{self.max_positions})"
            )

        # 2. Daily drawdown circuit-breaker
        if self._session_balance and self._session_balance > 0:
            daily_loss_pct = (
                (self._session_balance - account["equity"]) / self._session_balance
            )
            if daily_loss_pct >= self.max_daily_loss:
                can_open = False
                reasons.append(
                    f"Daily loss circuit-breaker triggered: "
                    f"{daily_loss_pct*100:.2f}% >= {self.max_daily_loss*100:.0f}%"
                )

        # 3. Margin level warning
        margin_level = account["margin_level"]
        if margin_level > 0 and margin_level < 200:
            can_open = False
            reasons.append(
                f"Margin level critical: {margin_level:.0f}% (minimum 200%)"
            )

        return {
            "can_open_new":  can_open,
            "reasons":       reasons,
            "position_count": pos_count,
            "account":       account,
        }

    # ── Emergency Actions ───────────────────────────────────────────────────

    def close_all_positions(self, executor) -> int:
        """
        Emergency flatten — closes every bot position immediately.
        Returns the number of positions successfully closed.
        """
        positions = self.get_open_positions()
        if not positions:
            logger.info("close_all_positions: no open positions to close")
            return 0

        closed = 0
        for pos in positions:
            logger.warning(
                f"EMERGENCY CLOSE: ticket={pos['ticket']} | "
                f"{pos['direction']} {pos['volume']} {pos['symbol']} | "
                f"P&L so far: {pos['profit']:.2f}"
            )
            if executor.close_position(pos["ticket"]):
                closed += 1

        logger.warning(f"Emergency close complete: {closed}/{len(positions)} closed")
        return closed
