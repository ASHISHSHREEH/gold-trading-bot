"""
MT5 Trade Executor
Responsible for translating a signal into a live broker order via MT5.

Key responsibilities:
  - ATR-based SL/TP calculation
  - Lot sizing from account risk %
  - Broker constraint enforcement (min lot, stops level, filling mode)
  - Order submission with requote retry
  - Position close
"""

import math
import logging
from typing import Dict, Any, Optional

import MetaTrader5 as mt5

from data.mt5_fetcher import MT5DataFetcher
import config

logger = logging.getLogger(__name__)

# Human-readable descriptions for every MT5 return code
_RETCODE_MSG: Dict[int, str] = {
    mt5.TRADE_RETCODE_DONE:               "Order executed successfully",
    mt5.TRADE_RETCODE_DONE_PARTIAL:       "Order partially filled",
    mt5.TRADE_RETCODE_REQUOTE:            "Requote — price changed",
    mt5.TRADE_RETCODE_REJECT:             "Order rejected by server",
    mt5.TRADE_RETCODE_CANCEL:             "Order cancelled by client",
    mt5.TRADE_RETCODE_PLACED:             "Order placed in queue",
    mt5.TRADE_RETCODE_ERROR:              "General error",
    mt5.TRADE_RETCODE_TIMEOUT:            "Order timed out",
    mt5.TRADE_RETCODE_INVALID:            "Invalid request",
    mt5.TRADE_RETCODE_INVALID_VOLUME:     "Invalid volume",
    mt5.TRADE_RETCODE_INVALID_PRICE:      "Invalid price",
    mt5.TRADE_RETCODE_INVALID_STOPS:      "Invalid stop levels",
    mt5.TRADE_RETCODE_TRADE_DISABLED:     "Trading disabled for this symbol",
    mt5.TRADE_RETCODE_MARKET_CLOSED:      "Market is closed",
    mt5.TRADE_RETCODE_NO_MONEY:           "Insufficient margin",
    mt5.TRADE_RETCODE_PRICE_CHANGED:      "Price changed during processing",
    mt5.TRADE_RETCODE_PRICE_OFF:          "Off quotes — no price",
    mt5.TRADE_RETCODE_TOO_MANY_REQUESTS:  "Too many requests — slow down",
    mt5.TRADE_RETCODE_SERVER_DISABLES_AT: "Auto-trading disabled by server",
    mt5.TRADE_RETCODE_CLIENT_DISABLES_AT: "Auto-trading disabled by terminal",
    mt5.TRADE_RETCODE_FROZEN:             "Order/position frozen",
    mt5.TRADE_RETCODE_INVALID_FILL:       "Invalid order fill mode",
    mt5.TRADE_RETCODE_CONNECTION:         "No connection to trade server",
    mt5.TRADE_RETCODE_NO_CHANGES:         "No changes to the order",
    mt5.TRADE_RETCODE_ONLY_REAL:          "Available on real accounts only",
    mt5.TRADE_RETCODE_LIMIT_ORDERS:       "Pending order limit reached",
    mt5.TRADE_RETCODE_LIMIT_VOLUME:       "Volume limit reached",
    mt5.TRADE_RETCODE_POSITION_CLOSED:    "Position already closed",
}


class MT5Executor:
    """
    Executes market orders through the MT5 terminal with full broker
    constraint handling, lot sizing, and requote retry logic.
    """

    def __init__(
        self,
        fetcher: MT5DataFetcher,
        risk_per_trade: float = config.RISK_PER_TRADE,
        magic: int            = config.MAGIC,
        slippage: int         = config.SLIPPAGE,
        max_retries: int      = 3,
    ):
        self.fetcher        = fetcher
        self.risk_per_trade = risk_per_trade
        self.magic          = magic
        self.slippage       = slippage
        self.max_retries    = max_retries
        self._filling_mode  = None   # detected once on first order

    # ── Public API ──────────────────────────────────────────────────────────

    def execute_signal(
        self,
        signal_data: Dict[str, Any],
        atr_value: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Main entry point. Takes a signal dict and ATR value, fires a
        market order if all pre-checks pass.

        Args:
            signal_data: Must contain 'signal' ('BUY'/'SELL'/'NEUTRAL')
                         and 'confidence' ('HIGH'/'MODERATE')
            atr_value:   Current ATR in price units (from ATRCalculator)

        Returns:
            Execution summary dict or None if trade was not placed.
        """
        signal = signal_data.get("signal", "NEUTRAL")
        if signal == "NEUTRAL":
            return None

        # Fetch live data
        tick     = self.fetcher.get_current_tick()
        sym_info = self.fetcher.get_symbol_info()
        account  = self.fetcher.get_account_info()

        if not all([tick, sym_info, account]):
            logger.error("Cannot execute: failed to fetch market data from MT5")
            return None

        # Direction + execution price
        if signal == "BUY":
            direction  = "LONG"
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick["ask"]          # BUY at ask
        else:
            direction  = "SHORT"
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick["bid"]          # SELL at bid

        # ATR-based SL/TP
        sl, tp = self._calculate_sl_tp(price, atr_value, direction, sym_info)
        if sl is None:
            return None

        # Lot size from risk %
        lot_size = self._calculate_lot_size(account, price, sl, sym_info)
        if lot_size is None:
            return None

        # Validate R:R before submitting
        rr = abs(tp - price) / abs(price - sl)
        if rr < config.MIN_RR_RATIO:
            logger.warning(
                f"R:R {rr:.2f} below minimum {config.MIN_RR_RATIO}. Trade skipped."
            )
            return None

        logger.info(
            f"Executing {direction} | Price: {price} | "
            f"SL: {sl} | TP: {tp} | Lots: {lot_size} | R:R: {rr:.2f}"
        )

        return self._place_order(
            order_type, price, lot_size, sl, tp, signal_data
        )

    def close_position(self, ticket: int) -> bool:
        """
        Close an open position by ticket number.
        Returns True on success.
        """
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.error(f"Position ticket {ticket} not found in MT5")
            return False

        pos  = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            logger.error(f"No tick data for {pos.symbol}")
            return False

        if pos.type == mt5.ORDER_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      pos.symbol,
            "volume":      pos.volume,
            "type":        close_type,
            "position":    ticket,
            "price":       price,
            "deviation":   self.slippage,
            "magic":       self.magic,
            "comment":     "GoldBot_Close",
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(pos.symbol),
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Position {ticket} closed at {result.price}")
            return True

        retcode = result.retcode if result else -1
        logger.error(
            f"Failed to close {ticket}: "
            f"{_RETCODE_MSG.get(retcode, f'retcode={retcode}')}"
        )
        return False

    # ── Internal helpers ────────────────────────────────────────────────────

    def _calculate_sl_tp(
        self,
        price: float,
        atr: float,
        direction: str,
        sym_info: Dict,
    ):
        """
        Compute SL/TP using ATR multipliers, then enforce the broker's
        minimum stop distance. Returns (sl, tp) or (None, None) on failure.
        """
        digits       = sym_info["digits"]
        point        = sym_info["point"]
        stops_level  = sym_info["stops_level"]                  # in points
        min_dist     = stops_level * point * 1.1                # 10% buffer

        sl_dist = atr * config.ATR_SL_MULT
        tp_dist = atr * config.ATR_TP_MULT

        # Enforce minimum broker stop distance
        if sl_dist < min_dist:
            logger.warning(
                f"ATR SL distance {sl_dist:.5f} < broker minimum {min_dist:.5f}. "
                f"Expanding to minimum."
            )
            sl_dist = min_dist
            tp_dist = sl_dist * config.ATR_TP_MULT / config.ATR_SL_MULT

        if direction == "LONG":
            sl = round(price - sl_dist, digits)
            tp = round(price + tp_dist, digits)
        else:
            sl = round(price + sl_dist, digits)
            tp = round(price - tp_dist, digits)

        # Final sanity checks
        if sl <= 0 or tp <= 0:
            logger.error(f"Invalid SL/TP calculated: SL={sl}, TP={tp}")
            return None, None

        return sl, tp

    def _calculate_lot_size(
        self,
        account: Dict,
        price: float,
        sl: float,
        sym_info: Dict,
    ) -> Optional[float]:
        """
        Lot size = Risk Amount / (SL distance × contract size)

        For XAUUSD:  contract_size = 100 oz/lot
        Risk amount = account balance × risk_per_trade %
        """
        balance       = account["balance"]
        risk_amount   = balance * self.risk_per_trade
        sl_distance   = abs(price - sl)
        contract_size = sym_info["contract_size"]

        if sl_distance == 0 or contract_size == 0:
            logger.error("Cannot size position: zero SL distance or contract size")
            return None

        raw_lots = risk_amount / (sl_distance * contract_size)

        # Snap to nearest lot step (floor — never risk more than intended)
        step = sym_info["volume_step"]
        lots = math.floor(raw_lots / step) * step
        lots = round(lots, 2)

        # Enforce broker min/max
        vol_min = sym_info["volume_min"]
        vol_max = sym_info["volume_max"]

        if lots < vol_min:
            logger.warning(
                f"Calculated lots {lots} < broker minimum {vol_min}. "
                f"Using minimum lot."
            )
            lots = vol_min

        lots = min(lots, vol_max)

        logger.info(
            f"Position sizing: balance={balance:.2f} | risk={risk_amount:.2f} "
            f"{account['currency']} | SL dist={sl_distance:.5f} | lots={lots}"
        )
        return lots

    def _place_order(
        self,
        order_type: int,
        price: float,
        volume: float,
        sl: float,
        tp: float,
        signal_data: Dict,
    ) -> Optional[Dict[str, Any]]:
        """
        Submit the order to MT5 with requote retry on price changes.
        """
        symbol       = self.fetcher.symbol
        confidence   = signal_data.get("confidence", "MOD")
        filling_mode = self._get_filling_mode(symbol)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    self.slippage,
            "magic":        self.magic,
            "comment":      f"GoldBot_{confidence[:3]}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        direction = "LONG" if order_type == mt5.ORDER_TYPE_BUY else "SHORT"

        for attempt in range(1, self.max_retries + 1):
            result = mt5.order_send(request)

            if result is None:
                logger.error(
                    f"order_send() returned None on attempt {attempt}: "
                    f"{mt5.last_error()}"
                )
                break

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    f"ORDER FILLED | ticket={result.order} | "
                    f"{direction} {volume} lots @ {result.price} | "
                    f"SL={sl} TP={tp}"
                )
                return {
                    "ticket":      result.order,
                    "symbol":      symbol,
                    "direction":   direction,
                    "entry_price": result.price,
                    "volume":      volume,
                    "stop_loss":   sl,
                    "take_profit": tp,
                    "confidence":  confidence,
                    "comment":     request["comment"],
                }

            # Requote — refresh price and retry
            if result.retcode == mt5.TRADE_RETCODE_REQUOTE:
                tick = mt5.symbol_info_tick(symbol)
                new_price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
                logger.warning(
                    f"Requote on attempt {attempt}/{self.max_retries}. "
                    f"Refreshing price: {request['price']} → {new_price}"
                )
                request["price"] = new_price
                continue

            # Non-retriable error — log and abort
            msg = _RETCODE_MSG.get(result.retcode, f"Unknown retcode {result.retcode}")
            logger.error(f"Order failed [{attempt}/{self.max_retries}]: {msg}")
            break

        return None

    def _get_filling_mode(self, symbol: str) -> int:
        """
        Detect the broker's supported order filling mode once and cache it.
        Some brokers support IOC, others FOK, others RETURN.
        """
        if self._filling_mode is not None:
            return self._filling_mode

        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC

        filling_type = info.filling_mode
        if filling_type & mt5.ORDER_FILLING_IOC:
            self._filling_mode = mt5.ORDER_FILLING_IOC
        elif filling_type & mt5.ORDER_FILLING_FOK:
            self._filling_mode = mt5.ORDER_FILLING_FOK
        else:
            self._filling_mode = mt5.ORDER_FILLING_RETURN

        logger.info(f"Filling mode detected: {self._filling_mode}")
        return self._filling_mode
