"""
MT5Executor — places and manages live orders through the MT5 API.

Handles:
  • New market orders (execute_signal)
  • Partial close at 1R (partial_close)
  • SL modification for breakeven / trailing (modify_position_sl)
  • Full position close (close_position)
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
    # Use getattr so missing constants on older MT5 builds don't crash at import
    names = (
        "TRADE_RETCODE_REQUOTE",
        "TRADE_RETCODE_PRICE_CHANGED",
        "TRADE_RETCODE_PRICE_OFF",
        "TRADE_RETCODE_OFF_QUOTES",
        "TRADE_RETCODE_CONNECTION",
        "TRADE_RETCODE_TIMEOUT",
    )
    return frozenset(
        getattr(mt5, name) for name in names if hasattr(mt5, name)
    )


class MT5Executor:

    def __init__(self, fetcher):
        self.fetcher = fetcher

    # ── Open Order ─────────────────────────────────────────────────────────────

    def execute_signal(
        self,
        signal: str,
        atr_value: float,
        symbol: str,
        risk_multiplier: float = 1.0,
        custom_sl: float = None,
    ) -> Optional[Dict[str, Any]]:
        if mt5 is None:
            return None

        tick     = self.fetcher.get_current_tick(symbol)
        sym_info = self.fetcher.get_symbol_info(symbol)
        acct     = self.fetcher.get_account_info()

        if not tick or not sym_info or not acct:
            logger.error(f"[{symbol}] Cannot execute: missing market data.")
            return None

        is_buy = signal.upper() == "BUY"
        price  = tick["ask"] if is_buy else tick["bid"]

        if custom_sl is not None:
            # Swing-based SL supplied — derive TP to maintain MIN_RR_RATIO
            sl        = custom_sl
            sl_dist   = abs(price - sl)
            tp        = price + sl_dist * config.MIN_RR_RATIO if is_buy else price - sl_dist * config.MIN_RR_RATIO
            digits    = sym_info["digits"]
            sl        = round(sl, digits)
            tp        = round(tp, digits)
        else:
            sl, tp = self._calculate_sl_tp(price, atr_value, is_buy, sym_info)
        if sl is None:
            return None

        rr = abs(tp - price) / abs(sl - price) if abs(sl - price) > 0 else 0
        if rr < config.MIN_RR_RATIO - 0.001:
            logger.warning(f"[{symbol}] R:R {rr:.2f} < {config.MIN_RR_RATIO}. Blocked.")
            return None

        lots = self._calculate_lots(price, sl, acct["balance"], sym_info, acct.get("currency", "USD"))
        if risk_multiplier != 1.0:
            lots = self._round_lots(lots * risk_multiplier, sym_info)
        if lots == 0.0:
            return None

        digits = sym_info["digits"]
        filling = self._filling_mode(symbol)
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lots,
            "type":         mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price":        round(price, digits),
            "sl":           round(sl, digits),
            "tp":           round(tp, digits),
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      f"GoldBot-{symbol[:6]}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        # Pre-flight margin check — catches "No money" and "Invalid stops" cheaply
        check = mt5.order_check(request)
        if check is None:
            logger.error(f"[{symbol}] order_check returned None: {mt5.last_error()}")
            return None
        if check.retcode not in (mt5.TRADE_RETCODE_DONE, 0):
            code_name = {
                10019: "No money (insufficient margin)",
                10016: "Invalid stops (broker min-distance rejected)",
            }.get(check.retcode, f"retcode={check.retcode}")
            logger.warning(
                f"[{symbol}] Pre-flight check FAILED — {code_name} "
                f"comment='{check.comment}' — skipping order."
            )
            return None

        result = self._send_with_retry(request, symbol)
        if result is None:
            return None

        logger.info(
            f"[{symbol}] EXECUTED {signal} ticket={result.order} "
            f"@ {result.price} | {result.volume} lots | "
            f"SL={round(sl,digits)} TP={round(tp,digits)} | "
            f"ATR={atr_value:.4f} R:R={rr:.2f}"
        )
        return {
            "ticket":      result.order,
            "symbol":      symbol,
            "direction":   signal.upper(),
            "entry_price": result.price,
            "volume":      result.volume,
            "stop_loss":   round(sl, digits),
            "take_profit": round(tp, digits),
            "atr":         atr_value,
            "risk_amount": round(acct["balance"] * config.RISK_PER_TRADE, 2),
            "rr_ratio":    round(rr, 2),
        }

    # ── Position Management ────────────────────────────────────────────────────

    def modify_position_sl(
        self,
        ticket: int,
        symbol: str,
        new_sl: float,
        new_tp: float,
    ) -> bool:
        """Move SL (and keep TP) on an open position — used for breakeven + trailing."""
        if mt5 is None:
            return False

        sym_info = self.fetcher.get_symbol_info(symbol)
        digits   = sym_info.get("digits", 5)

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   symbol,
            "position": ticket,
            "sl":       round(new_sl, digits),
            "tp":       round(new_tp, digits),
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"[{symbol}] ticket={ticket} SL updated → {round(new_sl, digits)}"
            )
            return True

        code = result.retcode if result else "None"
        logger.error(f"[{symbol}] SL modify failed retcode={code}")
        return False

    def partial_close(
        self,
        ticket: int,
        symbol: str,
        close_ratio: float = 0.5,
    ) -> bool:
        """
        Close a fraction of an open position (default 50 %) to lock in 1R profit.
        """
        if mt5 is None:
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"partial_close: ticket {ticket} not found.")
            return False

        pos      = positions[0]
        sym_info = self.fetcher.get_symbol_info(symbol)
        lot_step = sym_info["lot_step"]
        min_lot  = sym_info["min_lot"]

        # Round down to nearest lot_step
        raw_vol   = pos.volume * close_ratio
        close_vol = round((raw_vol // lot_step) * lot_step, 8)

        if close_vol < min_lot:
            logger.warning(
                f"[{symbol}] Partial close volume {close_vol} < min_lot {min_lot}. Skipped."
            )
            return False

        is_buy     = pos.type == mt5.POSITION_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        tick       = self.fetcher.get_current_tick(symbol)
        if not tick:
            return False

        close_price = tick["bid"] if is_buy else tick["ask"]

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       close_vol,
            "type":         close_type,
            "position":     ticket,
            "price":        close_price,
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      "GoldBot-PartialTP",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(symbol),
        }

        result = self._send_with_retry(request, symbol)
        if result:
            logger.info(
                f"[{symbol}] Partial close {close_vol} lots @ {close_price} "
                f"(ticket={ticket})"
            )
        return result is not None

    def close_position(self, ticket: int, symbol: str) -> bool:
        if mt5 is None:
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False

        pos        = positions[0]
        is_buy_pos = pos.type == mt5.POSITION_TYPE_BUY
        tick       = self.fetcher.get_current_tick(symbol)
        if not tick:
            return False

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL if is_buy_pos else mt5.ORDER_TYPE_BUY,
            "position":     ticket,
            "price":        tick["bid"] if is_buy_pos else tick["ask"],
            "deviation":    config.SLIPPAGE,
            "magic":        config.MAGIC,
            "comment":      "GoldBot-Close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(symbol),
        }

        result = self._send_with_retry(request, symbol)
        if result:
            logger.info(f"[{symbol}] Closed ticket={ticket}")
        return result is not None

    # ── Internal ───────────────────────────────────────────────────────────────

    def _calculate_sl_tp(self, price, atr, is_buy, sym_info):
        sl = price - atr * config.ATR_SL_MULT if is_buy else price + atr * config.ATR_SL_MULT
        tp = price + atr * config.ATR_TP_MULT if is_buy else price - atr * config.ATR_TP_MULT

        stops_level = sym_info.get("stops_level", 0)
        point       = sym_info.get("point", 0.00001)
        min_dist    = stops_level * point

        if min_dist > 0 and abs(price - sl) < min_dist:
            logger.debug(
                f"SL distance {abs(price-sl):.5f} < broker min {min_dist:.5f} "
                f"(stops_level={stops_level}, point={point}) — widening."
            )
            rr_mult = config.ATR_TP_MULT / config.ATR_SL_MULT
            sl = price - min_dist if is_buy else price + min_dist
            tp = price + min_dist * rr_mult if is_buy else price - min_dist * rr_mult

        return sl, tp

    def _filling_mode(self, symbol: str) -> int:
        """Return the filling mode supported by this symbol/broker.
        Checks the symbol's filling_mode bitmask: bit0=FOK, bit1=IOC, else RETURN."""
        if mt5 is None:
            return 2  # IOC fallback
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_RETURN
        fm = info.filling_mode
        if fm & 1:   # FOK supported
            return mt5.ORDER_FILLING_FOK
        if fm & 2:   # IOC supported
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN  # default — most brokers accept this

    def _get_fx_rate(self, account_currency: str) -> float:
        """
        Return live units of account_currency per 1 USD by querying MT5.
        Tries USDJPY, USDJPYm, USD/JPY style symbols in order.
        Falls back to config.ACCOUNT_FX_RATE if MT5 cannot provide the rate.
        """
        if mt5 is None or account_currency.upper() == "USD":
            return 1.0

        ccy = account_currency.upper()
        candidates = [
            f"USD{ccy}",
            f"USD{ccy}m",
            f"USD/{ccy}",
            f"USD.{ccy}",
        ]

        for sym in candidates:
            tick = mt5.symbol_info_tick(sym)
            if tick and tick.bid > 0:
                rate = (tick.bid + tick.ask) / 2.0
                logger.debug(f"Live FX rate from {sym}: 1 USD = {rate:.4f} {ccy}")
                return rate

        logger.debug(
            f"Could not fetch live USD/{ccy} rate from MT5 — "
            f"using config ACCOUNT_FX_RATE={config.ACCOUNT_FX_RATE}"
        )
        return config.ACCOUNT_FX_RATE

    def _calculate_lots(self, price, sl, balance, sym_info, account_currency: str = "USD") -> float:
        sl_distance   = abs(price - sl)
        contract_size = sym_info["contract_size"]
        if sl_distance == 0 or contract_size == 0:
            return 0.0

        # Convert account balance to USD using live FX rate.
        fx_rate     = self._get_fx_rate(account_currency)
        balance_usd = balance / fx_rate
        raw_lots    = (balance_usd * config.RISK_PER_TRADE) / (sl_distance * contract_size)
        return self._round_lots(raw_lots, sym_info)

    def _round_lots(self, raw: float, sym_info: dict) -> float:
        lot_step = sym_info["lot_step"]
        min_lot  = sym_info["min_lot"]
        max_lot  = sym_info["max_lot"]
        lots     = round((raw // lot_step) * lot_step, 8)
        if lots < min_lot:
            # Use broker minimum rather than skipping — accepts higher risk on demo.
            # ⚠️  REMINDER: Gold at 0.01 lots ≈ 3-4% risk (not 1%). Fix when
            #     account reaches ~$1,050 USD (≈165,000 JPY) for proper sizing.
            logger.warning(
                f"Lot {raw:.5f} < min {min_lot} — using min lot {min_lot} "
                f"(~{min_lot/raw*100:.0f}% of intended risk, demo only)."
            )
            return min_lot
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
                    d = self.fetcher.get_symbol_info(symbol).get("digits", 5)
                    request["price"] = round(
                        tick["ask"] if request["type"] == mt5.ORDER_TYPE_BUY
                        else tick["bid"], d
                    )
                time.sleep(delay)
                delay *= 2
                continue
            logger.error(
                f"[{symbol}] Rejected retcode={result.retcode} "
                f"comment='{result.comment}' "
                f"filling={request.get('type_filling')} "
                f"last_error={mt5.last_error()}"
            )
            return None

        logger.error(f"[{symbol}] Max retries exhausted.")
        return None
