"""
MT5PositionManager — reads live positions from the MT5 terminal.
Tracks positions across ALL configured symbols combined.
Risk gates are account-wide, not per-symbol.
"""
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger(__name__)


class MT5PositionManager:

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self._session_start_balance: float = 0.0

    def set_session_start_balance(self, balance: float):
        self._session_start_balance = balance
        logger.info(f"Session start balance locked at {balance:.2f}")

    # ── Position Queries ───────────────────────────────────────────────────────

    def get_open_positions(self, symbol: str = None) -> List[Dict[str, Any]]:
        """
        Return open positions opened by this bot (magic number filter).
        If symbol is given, filter to that symbol only.
        If symbol is None, return positions across ALL configured symbols.
        """
        if mt5 is None:
            return []

        result = []
        symbols_to_check = [symbol] if symbol else config.SYMBOLS

        for sym in symbols_to_check:
            raw = mt5.positions_get(symbol=sym)
            if raw is None:
                continue
            for p in raw:
                if p.magic != config.MAGIC:
                    continue
                result.append({
                    "ticket":        p.ticket,
                    "symbol":        p.symbol,
                    "direction":     "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "entry_price":   p.price_open,
                    "current_price": p.price_current,
                    "sl":            p.sl,
                    "tp":            p.tp,
                    "volume":        p.volume,
                    "profit":        p.profit,
                    "swap":          p.swap,
                    "open_time":     datetime.fromtimestamp(p.time),
                })
        return result

    def get_position_count(self, symbol: str = None) -> int:
        return len(self.get_open_positions(symbol))

    def has_position_for(self, symbol: str) -> bool:
        """True if there is already an open position for this symbol."""
        return self.get_position_count(symbol) > 0

    def get_pyramid_eligible(self, symbol: str, signal_direction: str, pos_state: dict) -> Optional[Dict]:
        """
        Returns the existing position if it qualifies for a pyramid add-on, else None.

        Conditions:
          - PYRAMID_ENABLED is True
          - Existing position in same symbol and same direction
          - Position is >= PYRAMID_MIN_R in profit (uses ATR stored in pos_state)
          - Not already pyramided (PYRAMID_MAX_ADDS limit)
        """
        if not config.PYRAMID_ENABLED:
            return None

        positions = self.get_open_positions(symbol)
        for pos in positions:
            if pos["direction"] != signal_direction:
                continue

            ticket = pos["ticket"]
            state  = pos_state.get(ticket, {})

            # Check add-on count
            adds_done = state.get("pyramid_adds", 0)
            if adds_done >= config.PYRAMID_MAX_ADDS:
                continue

            # Need ATR to measure R
            atr = state.get("atr")
            if not atr or atr <= 0:
                continue

            sl_distance   = abs(pos["entry_price"] - pos["sl"]) if pos["sl"] else atr * config.ATR_SL_MULT
            _si           = self.fetcher.get_symbol_info(pos["symbol"])
            _csize        = (_si.get("contract_size", 100) if _si else 100)
            r_achieved    = pos["profit"] / (sl_distance * pos["volume"] * _csize) if sl_distance > 0 else 0

            # Simpler check: price moved enough from entry
            price_move  = abs(pos["current_price"] - pos["entry_price"])
            r_in_price  = price_move / (atr * config.ATR_SL_MULT) if atr > 0 else 0

            if r_in_price >= config.PYRAMID_MIN_R:
                return pos

        return None

    # ── Risk Gates ─────────────────────────────────────────────────────────────

    def check_risk_limits(self, symbol: str = None, allow_pyramid: bool = False) -> Dict[str, Any]:
        """
        Account-wide three-layer risk gate.
        If allow_pyramid=True, skips the duplicate-symbol check (pyramiding path).

        Returns:
            { 'can_open_new': bool, 'reasons': list, 'position_count': int, 'account': dict }
        """
        all_positions = self.get_open_positions()
        acct          = self.fetcher.get_account_info()
        reasons       = []
        can_trade     = True

        # Gate 1 — max total positions across all symbols
        if len(all_positions) >= config.MAX_POSITIONS:
            reasons.append(
                f"Max positions reached ({len(all_positions)}/{config.MAX_POSITIONS})"
            )
            can_trade = False

        # Gate 2 — no duplicate position in same symbol (skipped on pyramid path)
        if symbol and not allow_pyramid and self.has_position_for(symbol):
            reasons.append(f"Already have an open position in {symbol}")
            can_trade = False

        if acct:
            # Gate 3 — daily drawdown circuit-breaker
            if self._session_start_balance > 0:
                drawdown = (
                    self._session_start_balance - acct["equity"]
                ) / self._session_start_balance

                if drawdown >= config.MAX_DAILY_LOSS:
                    reasons.append(
                        f"Daily drawdown {drawdown:.1%} >= "
                        f"{config.MAX_DAILY_LOSS:.1%} circuit-breaker"
                    )
                    can_trade = False

            # Gate 4 — margin safety
            ml = acct["margin_level"]
            if ml > 0 and ml < 200:
                reasons.append(f"Margin level critical: {ml:.0f}% (need > 200%)")
                can_trade = False

        return {
            "can_open_new":   can_trade,
            "reasons":        reasons,
            "position_count": len(all_positions),
            "account":        acct,
        }

    # ── Closed Deal Detection (for AI online learning) ─────────────────────────

    def get_recently_closed_deals(
        self,
        since_epoch: float,
        magic: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query MT5 deal history for closed deals since a given unix timestamp.
        Used by the AI learning engine to detect position closes and retrieve
        realised P&L, entry/exit prices.

        Args:
            since_epoch : unix timestamp to search from
            magic       : filter by magic number (defaults to config.MAGIC)

        Returns:
            list of deal dicts with keys:
              ticket, order, symbol, direction, entry_price, exit_price,
              profit, volume, close_time_epoch, rr_achieved (if SL known)
        """
        if mt5 is None:
            return []

        use_magic = magic if magic is not None else config.MAGIC
        from datetime import datetime, timezone

        try:
            from_dt = datetime.fromtimestamp(since_epoch, tz=timezone.utc)
            to_dt   = datetime.now(timezone.utc)
            deals   = mt5.history_deals_get(from_dt, to_dt)
        except Exception as exc:
            logger.warning("get_recently_closed_deals: MT5 query failed — %s", exc)
            return []

        if deals is None:
            return []

        results = []
        for d in deals:
            if d.magic != use_magic:
                continue
            # Only closing deals (entry_type == DEAL_ENTRY_OUT or DEAL_ENTRY_INOUT)
            if not hasattr(mt5, "DEAL_ENTRY_OUT"):
                continue
            if d.entry not in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                continue

            direction = "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL"
            results.append({
                "ticket":            d.position_id,
                "deal_ticket":       d.ticket,
                "symbol":            d.symbol,
                "direction":         direction,
                "exit_price":        d.price,
                "profit":            d.profit,
                "volume":            d.volume,
                "close_time_epoch":  float(d.time),
                "comment":           d.comment,
            })

        return results

    def get_deal_for_position(self, position_ticket: int) -> Optional[Dict[str, Any]]:
        """
        Fetch the closing deal for a position by position ID — more reliable than a
        time-range query when the close time is unknown or the bulk scan misses it.
        """
        if mt5 is None:
            return None
        try:
            deals = mt5.history_deals_get(position=position_ticket)
        except Exception as exc:
            logger.warning("get_deal_for_position(%d): MT5 query failed — %s", position_ticket, exc)
            return None
        if not deals:
            return None

        for d in deals:
            if d.magic != config.MAGIC:
                continue
            if not hasattr(mt5, "DEAL_ENTRY_OUT"):
                break
            if d.entry not in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                continue
            direction = "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL"
            return {
                "ticket":           d.position_id,
                "deal_ticket":      d.ticket,
                "symbol":           d.symbol,
                "direction":        direction,
                "exit_price":       d.price,
                "profit":           d.profit,
                "volume":           d.volume,
                "close_time_epoch": float(d.time),
                "comment":          d.comment,
            }
        return None

    # ── Emergency Flatten ──────────────────────────────────────────────────────

    def close_all_positions(self, executor) -> int:
        """Close every position across all symbols opened by this bot."""
        positions = self.get_open_positions()
        closed    = 0
        for pos in positions:
            logger.warning(
                f"EMERGENCY CLOSE: {pos['symbol']} ticket={pos['ticket']} "
                f"{pos['direction']} profit={pos['profit']:.2f}"
            )
            if executor.close_position(pos["ticket"], pos["symbol"]):
                closed += 1
        logger.warning(f"Emergency flatten: {closed}/{len(positions)} closed.")
        return closed
