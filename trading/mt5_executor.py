"""
MT5Executor — places live market orders through mt5.order_send().

Design principles (learned from production FX desks):
  • Never hardcode prices; always refresh tick before each attempt.
  • Lot sizing derived from account risk, not arbitrary fixed size.
  • Broker's minimum stop distance is enforced before every order.
  • Requotes / price-off errors are retried with exponential back-off.
  • R:R gate blocks any trade that doesn't meet MIN_RR_RATIO.
"""
import logging
import time
from typing import Optional, Dict, Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger(__name__)

# Retryable MT5 return codes (price moved; try again with fresh quote)
_RETRYABLE = frozenset()  # populated at runtime once mt5 is confirmed available


def _retryable_codes():
    if mt5 is None:
        return frozenset()
    return frozenset({
        mt5.TRADE_RETCODE_REQUOTE,
        mt5.TRADE_RETCODE_PRICE_CHANGED,
        mt5.TRADE_RETCODE_PRICE_OFF,
        mt5.TRADE_RETCODE_OFF_QUOTES,
        mt5.TRADE_RETCODE_CONNECTION,
        mt5.TRADE_RETCODE_TIMEOUT,
    })


class MT5Executor:
    """
    Stateless execution engine.  One instance lives for the whole session.
    Requires a connected MT5DataFetcher passed at construction.
    """

    def __init__(self, fetcher):
        self.fetcher = fetcher

    # ── Public API ─────────────────────────────────────────────────────────────

    def execute_signal(
        self,
        signal: str,
        atr_value: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Open a market order.

        Args:
            signal:    'BUY' or 'SELL'
            atr_value: current ATR in price units (from ATRCalculator.get_latest)

        Returns:
            Execution dict on success, None on any failure.
        """
        if mt5 is None:
            logger.critical("MetaTrader5 not installed.")
            return None

        tick     = self.fetcher.get_current_tick()
        sym_info = self.fetcher.get_symbol_info()
        acct     = self.fetcher.get_account_info()

        if not tick or not sym_info or not acct:
            logger.error("Cannot execute: missing tick / symbol / account data.")
            return None

        is_buy = signal.upper() == "BUY"
        price  = tick["ask"] if is_buy else tick["bid"]

        sl, tp = self._calculate_sl_tp(price, atr_value, is_buy, sym_info)
        if sl is None:
            return None

        rr = abs(tp - price) / abs(sl - price)
        if rr < config.MIN_RR_RATIO:
            logger.warning(f"R:R {rr:.2f} < MIN {config.MIN_RR_RATIO}. Order blocked.")
            return None

        lots = self._calculate_lots(price, sl, acct["balance"], sym_info)
        if lots == 0.0:
            return None

        digits     = sym_info["digits"]
        price      = round(price, digits)
        sl         = round(sl,    digits)
        tp         = round(tp,    digits)
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       config.SYMBOL,
            "volume":       lots,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      "GoldBot-ATR",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = self._send_with_retry(request)
        if result is None:
            return None

        risk_amount = acct["balance"] * config.RISK_PER_TRADE
        logger.info(
            f"EXECUTED {signal} | ticket={result.order} "
            f"@ {result.price} | vol={result.volume} lots | "
            f"SL={sl} TP={tp} | ATR={atr_value:.2f} R:R={rr:.2f}"
        )
        return {
            "ticket":      result.order,
            "symbol":      config.SYMBOL,
            "direction":   signal.upper(),
            "entry_price": result.price,
            "volume":      result.volume,
            "stop_loss":   sl,
            "take_profit": tp,
            "atr":         atr_value,
            "risk_amount": round(risk_amount, 2),
            "rr_ratio":    round(rr, 2),
        }

    def close_position(self, ticket: int) -> bool:
        """Close a specific position by ticket number."""
        if mt5 is None:
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"Position {ticket} not found for close.")
            return False

        pos        = positions[0]
        is_buy_pos = pos.type == mt5.POSITION_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy_pos else mt5.ORDER_TYPE_BUY

        tick = self.fetcher.get_current_tick()
        if not tick:
            logger.error("Cannot close: no tick data.")
            return False

        close_price = tick["bid"] if is_buy_pos else tick["ask"]

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       config.SYMBOL,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     ticket,
            "price":        close_price,
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      "GoldBot-Close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = self._send_with_retry(request)
        if result:
            logger.info(f"Closed ticket={ticket} @ {close_price}")
        return result is not None

    # ── Internal Helpers ───────────────────────────────────────────────────────

    def _calculate_sl_tp(self, price, atr, is_buy, sym_info):
        """Compute SL/TP and enforce broker minimum stop distance."""
        if is_buy:
            sl = price - atr * config.ATR_SL_MULT
            tp = price + atr * config.ATR_TP_MULT
        else:
            sl = price + atr * config.ATR_SL_MULT
            tp = price - atr * config.ATR_TP_MULT

        # Broker minimum stop distance in price units
        min_dist = sym_info["stops_level"] * sym_info["point"]
        if min_dist > 0 and abs(price - sl) < min_dist:
            sl = price - min_dist if is_buy else price + min_dist
            tp_mult = config.ATR_TP_MULT / config.ATR_SL_MULT
            tp = price + min_dist * tp_mult if is_buy else price - min_dist * tp_mult
            logger.debug(f"SL adjusted to broker minimum: min_dist={min_dist}")

        return sl, tp

    def _calculate_lots(self, price, sl, balance, sym_info) -> float:
        """
        Lot sizing formula (institutional standard):
            lots = (balance × risk_pct) / (sl_distance × contract_size)
        """
        sl_distance   = abs(price - sl)
        contract_size = sym_info["contract_size"]

        if sl_distance == 0 or contract_size == 0:
            logger.error("Cannot size position: zero SL distance or contract size.")
            return 0.0

        risk_amount = balance * config.RISK_PER_TRADE
        raw_lots    = risk_amount / (sl_distance * contract_size)

        return self._round_lots(raw_lots, sym_info)

    def _round_lots(self, raw: float, sym_info: dict) -> float:
        min_lot  = sym_info["min_lot"]
        max_lot  = sym_info["max_lot"]
        lot_step = sym_info["lot_step"]

        # Snap to nearest lot_step (always round down to avoid over-risking)
        lots = (raw // lot_step) * lot_step
        lots = round(lots, 8)   # floating-point cleanup

        if lots < min_lot:
            logger.warning(
                f"Calculated {raw:.5f} lots < min {min_lot}. Position skipped."
            )
            return 0.0
        return min(lots, max_lot)

    def _send_with_retry(self, request: dict, max_retries: int = 3):
        retryable = _retryable_codes()
        delay     = 1.0

        for attempt in range(1, max_retries + 1):
            result = mt5.order_send(request)
            if result is None:
                logger.error(f"order_send returned None: {mt5.last_error()}")
                return None

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return result

            if result.retcode in retryable:
                logger.warning(
                    f"Retryable code {result.retcode} (attempt {attempt}/{max_retries}). "
                    f"Refreshing price, retrying in {delay:.0f}s..."
                )
                # Refresh price so the next attempt uses current market
                tick = self.fetcher.get_current_tick()
                if tick and "price" in request:
                    sym_info = self.fetcher.get_symbol_info()
                    digits   = sym_info.get("digits", 5)
                    if request["type"] == mt5.ORDER_TYPE_BUY:
                        request["price"] = round(tick["ask"], digits)
                    else:
                        request["price"] = round(tick["bid"], digits)

                time.sleep(delay)
                delay *= 2
                continue

            logger.error(
                f"Order rejected | retcode={result.retcode} | {result.comment}"
            )
            return None

        logger.error("Max retries exhausted. Order abandoned.")
        return None
