"""
Position Manager Module
Handles real-time monitoring of open positions, executes automated
Stop Loss and Take Profit orders, and updates portfolio valuation.
"""

import logging
import sys
import os
from typing import Dict, Any, List, Optional

# --- PATH FIX FOR DIRECT EXECUTION ---
# This allows you to run 'python trading/position_manager.py' directly
# by adding the project root to the Python path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.schema import TradingDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PositionManager:
    """
    Manages active trading positions.
    
    Responsibilities:
    1. Monitor open positions against current market prices
    2. Execute automated exits (Stop Loss / Take Profit)
    3. Calculate Unrealized P&L
    4. Enforce Risk Limits
    """

    def __init__(self, db: TradingDatabase):
        """
        Initialize the Position Manager.
        
        Args:
            db (TradingDatabase): Active database connection instance
        """
        self.db = db
        logger.info("PositionManager initialized connected to TradingDatabase")

    def update_all_positions(self, current_prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Main update loop: updates prices, checks triggers, and closes positions.
        """
        positions = self.db.get_open_positions()
        
        result = {
            'updated': 0,
            'closed': 0,
            'stop_loss_hits': [],
            'take_profit_hits': [],
            'errors': []
        }

        for pos in positions:
            symbol = pos['symbol']
            
            # Check if we have price data for this position
            if symbol not in current_prices:
                error_msg = f"No price available for {symbol}, skipping position #{pos['id']}"
                # Only log error once per missing symbol to avoid spamming logs
                if error_msg not in result['errors']:
                    result['errors'].append(error_msg)
                    logger.warning(error_msg)
                continue

            current_price = current_prices[symbol]
            pos_id = pos['id']
            
            # 1. Update latest price in database
            if self.db.update_position_price(pos_id, current_price):
                result['updated'] += 1
            else:
                msg = f"Failed to update database for position #{pos_id}"
                result['errors'].append(msg)
                logger.error(msg)
                continue

            # 2. Check Stop Loss
            if self._check_stop_loss(pos, current_price):
                # NOTE: In real trading, we would fetch the execution price. 
                # For paper trading, using current_price (trigger price) is acceptable.
                trade = self.db.close_position(pos_id, current_price, exit_reason="Stop Loss")
                if trade:
                    result['closed'] += 1
                    hit_info = {
                        'symbol': symbol,
                        'direction': pos['direction'],
                        'pnl': trade['pnl']
                    }
                    result['stop_loss_hits'].append(hit_info)
                    logger.warning(f"🛑 STOP LOSS HIT: {symbol} {pos['direction']} @ {current_price} | P&L: {trade['pnl']:.2f}")
                else:
                    logger.error(f"Failed to close position #{pos_id} after SL trigger")
                continue # Position closed, move to next

            # 3. Check Take Profit
            if self._check_take_profit(pos, current_price):
                trade = self.db.close_position(pos_id, current_price, exit_reason="Take Profit")
                if trade:
                    result['closed'] += 1
                    hit_info = {
                        'symbol': symbol,
                        'direction': pos['direction'],
                        'pnl': trade['pnl']
                    }
                    result['take_profit_hits'].append(hit_info)
                    logger.info(f"✅ TAKE PROFIT HIT: {symbol} {pos['direction']} @ {current_price} | P&L: {trade['pnl']:.2f}")
                else:
                    logger.error(f"Failed to close position #{pos_id} after TP trigger")
                continue

        # 4. Update Portfolio Level Stats
        self._update_portfolio_unrealized()
        
        return result

    def _check_stop_loss(self, position: Dict[str, Any], current_price: float) -> bool:
        """Check if Stop Loss condition is met."""
        sl = position.get('stop_loss')
        if sl is None or sl == 0:
            return False

        direction = position['direction']
        
        if direction == "LONG":
            return current_price <= sl
        elif direction == "SHORT":
            return current_price >= sl
        
        return False

    def _check_take_profit(self, position: Dict[str, Any], current_price: float) -> bool:
        """Check if Take Profit condition is met."""
        tp = position.get('take_profit')
        if tp is None or tp == 0:
            return False

        direction = position['direction']
        
        if direction == "LONG":
            return current_price >= tp
        elif direction == "SHORT":
            return current_price <= tp
        
        return False

    def _update_portfolio_unrealized(self):
        """Recalculates total unrealized P&L and updates portfolio."""
        positions = self.db.get_open_positions()
        
        total_unrealized = sum(p['unrealized_pnl'] for p in positions)
        
        portfolio = self.db.get_portfolio()
        if not portfolio:
            return

        # Equity = Balance + Unrealized P&L
        new_equity = portfolio['balance'] + total_unrealized
        
        # Free Margin = Equity - Margin Used
        new_free_margin = new_equity - portfolio['margin_used']

        self.db.update_portfolio(
            equity=new_equity,
            unrealized_pnl=total_unrealized,
            free_margin=new_free_margin
        )

    def get_position_summary(self) -> Dict[str, Any]:
        """Get a summary of all active positions."""
        positions = self.db.get_open_positions()
        count = len(positions)
        total_unrealized = sum(p['unrealized_pnl'] for p in positions)
        
        return {
            'count': count,
            'total_unrealized_pnl': total_unrealized,
            'positions': positions
        }

    def close_position_manual(self, position_id: int, exit_price: float, reason: str = "Manual Close") -> Optional[Dict[str, Any]]:
        """Manually close a specific position."""
        trade = self.db.close_position(position_id, exit_price, exit_reason=reason)
        
        if trade:
            self._update_portfolio_unrealized()
            logger.info(f"Manual Close: Position #{position_id} closed at {exit_price} | P&L: {trade['pnl']:.2f}")
            return trade
        
        logger.error(f"Failed to manually close position #{position_id}")
        return None

    def close_all_positions(self, current_prices: Dict[str, float], reason: str = "Close All") -> List[Dict[str, Any]]:
        """Emergency close all positions at current market prices."""
        positions = self.db.get_open_positions()
        closed_trades = []
        
        for pos in positions:
            symbol = pos['symbol']
            if symbol in current_prices:
                price = current_prices[symbol]
                trade = self.db.close_position(pos['id'], price, exit_reason=reason)
                if trade:
                    closed_trades.append(trade)
            else:
                logger.error(f"Cannot close position #{pos['id']} ({symbol}): No price data available")

        if closed_trades:
            self._update_portfolio_unrealized()
            logger.info(f"Mass Close: Closed {len(closed_trades)} positions. Reason: {reason}")
            
        return closed_trades

    def check_risk_limits(self, max_positions: int = 3, max_loss_pct: float = 0.05) -> Dict[str, Any]:
        """Check if the account allows for opening new positions."""
        portfolio = self.db.get_portfolio()
        positions = self.db.get_open_positions()
        
        if not portfolio:
             return {'can_open_new': False, 'reasons': ["Portfolio data unavailable"]}

        current_pos_count = len(positions)
        reasons = []
        can_open = True
        
        # 1. Position Count Check
        if current_pos_count >= max_positions:
            can_open = False
            reasons.append(f"Max positions reached ({current_pos_count}/{max_positions})")
            
        # 2. Max Loss Check (Drawdown Protection)
        equity = portfolio['equity']
        balance = portfolio['balance']
        
        # Calculate Drawdown Limit based on current Balance
        drawdown_limit = balance * (1 - max_loss_pct)
        
        if equity < drawdown_limit:
            can_open = False
            current_drawdown_pct = ((balance - equity) / balance) * 100
            reasons.append(f"Max drawdown limit hit ({current_drawdown_pct:.2f}% > {max_loss_pct*100:.2f}%)")

        return {
            'can_open_new': can_open,
            'position_count': current_pos_count,
            'max_positions': max_positions,
            'equity': equity,
            'drawdown_limit': drawdown_limit,
            'reasons': reasons
        }

# --- TESTING BLOCK ---
if __name__ == "__main__":
    print("🧪 STARTING POSITION MANAGER TEST (WITH PATH FIX)...")
    
    # 1. Setup Test DB
    test_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "position_test.db")
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        
    db = TradingDatabase(test_db_path)
    pm = PositionManager(db)
    
    print("\n📝 Opening 3 Test Positions...")
    db.open_position("XAU_JPY", "LONG", 4500.0, 1.0, 4450.0, 4600.0, "Test", "HIGH")
    db.open_position("XAU_JPY", "SHORT", 4500.0, 1.0, 4550.0, 4400.0, "Test", "HIGH")
    db.open_position("USD_JPY", "LONG", 150.0, 100.0, 149.0, 152.0, "Test", "MODERATE")
    
    # ---------------------------------------------------------
    # Test 1: Stop Loss Hit (Pos 1)
    # ---------------------------------------------------------
    print("\n🛑 Test 1: Stop Loss Trigger")
    prices_sl = {"XAU_JPY": 4440.0, "USD_JPY": 150.50}
    res_sl = pm.update_all_positions(prices_sl)
    print(f"Closed: {res_sl['closed']} (Expected 1)")

    # ---------------------------------------------------------
    # Test 2: Take Profit Hit (Pos 2)
    # ---------------------------------------------------------
    print("\n✅ Test 2: Take Profit Trigger")
    prices_tp = {"XAU_JPY": 4390.0, "USD_JPY": 150.50}
    res_tp = pm.update_all_positions(prices_tp)
    print(f"Closed: {res_tp['closed']} (Expected 1)")

    # ---------------------------------------------------------
    # Final Checks
    # ---------------------------------------------------------
    print("\n📊 Final Report")
    summary = pm.get_position_summary()
    print(f"Remaining Positions: {summary['count']} (Expected 1)")
    
    # Cleanup
    db.close()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    print("\n✅ Position Manager Test Complete!")