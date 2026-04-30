"""
MT5PositionManager — reads live positions from the MT5 terminal.

Responsibilities:
  • List all open positions filtered by our magic number
  • Enforce the three risk gates: max-positions, daily-drawdown, margin-level
  • Emergency flatten (close-all) when circuit-breakers trip
"""
import logging
from datetime import datetime
from typing import Dict, List, Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger(__name__)


class MT5PositionManager:
    """
    Stateful only in that it remembers the session-start balance for the
    daily drawdown calculation.  Everything else is queried live from MT5.
    """

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self._session_start_balance: float = 0.0

    def set_session_start_balance(self, balance: float):
        self._session_start_balance = balance
        logger.info(f"Session start balance locked at {balance:.2f}")

    # ── Position Queries ───────────────────────────────────────────────────────

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Return all positions opened by this bot (magic number filter)."""
        if mt5 is None:
            return []

        raw = mt5.positions_get(symbol=config.SYMBOL)
        if raw is None:
            return []

        result = []
        for p in raw:
            if p.magic != config.MAGIC:
                continue
            result.append({
                "ticket":        p.ticket,
                "direction":     "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "entry_price":   p.price_open,
                "current_price": p.price_current,
                "sl":            p.sl,
                "tp":            p.tp,
                "volume":        p.volume,
                "profit":        p.profit,
                "swap":          p.swap,
                "open_time":     datetime.fromtimestamp(p.time),
                "comment":       p.comment,
            })
        return result

    def get_position_count(self) -> int:
        return len(self.get_open_positions())

    # ── Risk Gates ─────────────────────────────────────────────────────────────

    def check_risk_limits(self) -> Dict[str, Any]:
        """
        Three-layer risk gate called before every new entry attempt.

        Returns:
            {
                'can_open_new': bool,
                'reasons':      list[str],
                'position_count': int,
                'account':      dict,
            }
        """
        positions = self.get_open_positions()
        acct      = self.fetcher.get_account_info()
        reasons   = []
        can_trade = True

        # Gate 1 — max concurrent positions
        if len(positions) >= config.MAX_POSITIONS:
            reasons.append(
                f"Max positions reached ({len(positions)}/{config.MAX_POSITIONS})"
            )
            can_trade = False

        if acct:
            # Gate 2 — daily drawdown circuit-breaker
            if self._session_start_balance > 0:
                drawdown = (
                    self._session_start_balance - acct["equity"]
                ) / self._session_start_balance

                if drawdown >= config.MAX_DAILY_LOSS:
                    reasons.append(
                        f"Daily drawdown {drawdown:.1%} >= "
                        f"{config.MAX_DAILY_LOSS:.1%} circuit-breaker fired"
                    )
                    can_trade = False

            # Gate 3 — margin safety (skip if no positions → margin_level = 0)
            ml = acct["margin_level"]
            if ml > 0 and ml < 200:
                reasons.append(f"Margin level critical: {ml:.0f}% (need > 200%)")
                can_trade = False

        return {
            "can_open_new":    can_trade,
            "reasons":         reasons,
            "position_count":  len(positions),
            "account":         acct,
        }

    # ── Emergency Flatten ──────────────────────────────────────────────────────

    def close_all_positions(self, executor) -> int:
        """
        Close every position opened by this bot immediately.
        Used when daily drawdown circuit-breaker trips.
        Returns number of successfully closed positions.
        """
        positions = self.get_open_positions()
        closed    = 0
        for pos in positions:
            logger.warning(
                f"EMERGENCY CLOSE: ticket={pos['ticket']} "
                f"{pos['direction']} profit={pos['profit']:.2f}"
            )
            if executor.close_position(pos["ticket"]):
                closed += 1
        logger.warning(f"Emergency flatten complete: {closed}/{len(positions)} closed.")
        return closed
