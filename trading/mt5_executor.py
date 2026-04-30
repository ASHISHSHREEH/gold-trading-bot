"""
MT5Executor — places live market orders through mt5.order_send().
Fully symbol-aware: every method takes an explicit symbol argument
so the same executor handles GOLD, indices, and FX identically.
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

    def __init__(self, fetcher):
        self.fetcher = fetcher

    # ── Public API ─────────────────────────────────────────────────────────────

    def execute_signal(
        self,
        signal: str,
        atr_value: float,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Open a market order for the given symbol.

        Args:
            signal:    'BUY' or 'SELL'
            atr_value: current ATR in price units
            symbol:    MT5 symbol name (e.g. 'GOLD', '#USSPX500')
        """
        if mt5 is None:
            logger.critical("MetaTrader5 not installed.")
            return None

        tick     = self.fetcher.get_current_tick(symbol)
        sym_info = self.fetcher.get_symbol_info(symbol)
        acct     = self.fetcher.get_account_info()

        if not tick or not sym_info or not acct:
            logger.error(f"[{symbol}] Cannot execute: missing market data.")
            return None

        is_buy = signal.upper() == "BUY"
        price  = tick["ask"] if is_buy else tick["bid"]

        sl, tp = self._calculate_sl_tp(price, atr_value, is_buy, sym_info)
        if sl is None:
            return None

        rr = abs(tp - price) / abs(sl - price) if abs(sl - price) > 0 else 0
        if rr < config.MIN_RR_RATIO:
            logger.warning(f"[{symbol}] R:R {rr:.2f} < MIN {config.MIN_RR_RATIO}. Blocked.")
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
            "symbol":       symbol,
            "volume":       lots,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      f"GoldBot-{symbol[:6]}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = self._send_with_retry(request, symbol)
        if result is None:
            return None

        risk_amount = acct["balance"] * config.RISK_PER_TRADE
        logger.info(
            f"[{symbol}] EXECUTED {signal} | ticket={result.order} "
            f"@ {result.price} | vol={result.volume} lots | "
            f"SL={sl} TP={tp} | ATR={atr_value:.4f} R:R={rr:.2f}"
        )
        return {
            "ticket":      result.order,
            "symbol":      symbol,
            "direction":   signal.upper(),
            "entry_price": result.price,
            "volume":      result.volume,
            "stop_loss":   sl,
            "take_profit": tp,
            "atr":         atr_value,
            "risk_amount": round(risk_amount, 2),
            "rr_ratio":    round(rr, 2),
        }

    def close_position(self, ticket: int, symbol: str) -> bool:
        if mt5 is None:
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"Position {ticket} not found.")
            return False

        pos        = positions[0]
        is_buy_pos = pos.type == mt5.POSITION_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy_pos else mt5.ORDER_TYPE_BUY

        tick = self.fetcher.get_current_tick(symbol)
        if not tick:
            return False

        close_price = tick["bid"] if is_buy_pos else tick["ask"]

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
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

        result = self._send_with_retry(request, symbol)
        if result:
            logger.info(f"[{symbol}] Closed ticket={ticket} @ {close_price}")
        return result is not None

    # ── Internal Helpers ───────────────────────────────────────────────────────

    def _calculate_sl_tp(self, price, atr, is_buy, sym_info):
        sl = price - atr * config.ATR_SL_MULT if is_buy else price + atr * config.ATR_SL_MULT
        tp = price + atr * config.ATR_TP_MULT if is_buy else price - atr * config.ATR_TP_MULT

        min_dist = sym_info["stops_level"] * sym_info["point"]
        if min_dist > 0 and abs(price - sl) < min_dist:
            sl = price - min_dist if is_buy else price + min_dist
            tp_mult = config.ATR_TP_MULT / config.ATR_SL_MULT
            tp = price + min_dist * tp_mult if is_buy else price - min_dist * tp_mult

        return sl, tp

    def _calculate_lots(self, price, sl, balance, sym_info) -> float:
        sl_distance   = abs(price - sl)
        contract_size = sym_info["contract_size"]

        if sl_distance == 0 or contract_size == 0:
            logger.error("Cannot size: zero SL distance or contract size.")
            return 0.0

        risk_amount = balance * config.RISK_PER_TRADE
        raw_lots    = risk_amount / (sl_distance * contract_size)
        return self._round_lots(raw_lots, sym_info)

    def _round_lots(self, raw: float, sym_info: dict) -> float:
        min_lot  = sym_info["min_lot"]
        max_lot  = sym_info["max_lot"]
        lot_step = sym_info["lot_step"]

        lots = (raw // lot_step) * lot_step
        lots = round(lots, 8)

        if lots < min_lot:
            logger.warning(f"Lot size {raw:.5f} < min {min_lot}. Skipping.")
            return 0.0
        return min(lots, max_lot)

    def _send_with_retry(self, request: dict, symbol: str, max_retries: int = 3):
        retryable = _retryable_codes()
        delay     = 1.0

        for attempt in range(1, max_retries + 1):
            result = mt5.order_send(request)
            if result is None:
                logger.error(f"[{symbol}] order_send None: {mt5.last_error()}")
                return None

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return result

            if result.retcode in retryable:
                logger.warning(
                    f"[{symbol}] Retryable {result.retcode} "
                    f"(attempt {attempt}/{max_retries}). Retry in {delay:.0f}s..."
                )
                tick = self.fetcher.get_current_tick(symbol)
                if tick and "price" in request:
                    sym_info = self.fetcher.get_symbol_info(symbol)
                    digits   = sym_info.get("digits", 5)
                    request["price"] = round(
                        tick["ask"] if request["type"] == mt5.ORDER_TYPE_BUY else tick["bid"],
                        digits
                    )
                time.sleep(delay)
                delay *= 2
                continue

            logger.error(f"[{symbol}] Order rejected {result.retcode}: {result.comment}")
            return None

        logger.error(f"[{symbol}] Max retries exhausted.")
        return None
