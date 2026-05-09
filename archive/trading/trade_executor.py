"""
Trade Executor Module
Responsible for executing trading signals, calculating trade parameters (SL/TP),
validating against risk rules, and persisting trades to the database.
"""

import logging
import sys
import os
from typing import Dict, Any, Optional

# Add parent directory to path for direct execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.schema import TradingDatabase
from trading.risk_manager import RiskManager
from trading.position_manager import PositionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TradeExecutor:
    """
    Executes trading signals by coordinating between Risk Manager,
    Position Manager, and the Database.
    """

    def __init__(self, db: TradingDatabase, risk_manager: RiskManager, position_manager: PositionManager):
        """
        Initialize the Trade Executor.

        Args:
            db (TradingDatabase): Database instance
            risk_manager (RiskManager): Risk management logic
            position_manager (PositionManager): Open position tracking
        """
        self.db = db
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        logger.info("TradeExecutor initialized")

    def execute_signal(self, signal_data: Dict[str, Any], current_price: float, symbol: str = "XAU_JPY") -> Optional[Dict[str, Any]]:
        """
        Main execution method - takes a signal and attempts to open a position.

        Args:
            signal_data (dict): Signal details. MUST contain 'signal'. 
                                Optionally 'entry_analysis' for volatility calc.
            current_price (float): Current market price
            symbol (str): Trading symbol

        Returns:
            dict: Execution summary if successful, None otherwise
        """
        try:
            # 1. Check if signal is actionable
            signal_type = signal_data.get('signal', 'NEUTRAL')
            if signal_type == "NEUTRAL":
                # logger.debug(f"Signal is NEUTRAL for {symbol}. No execution.")
                return None

            # 2. Check risk limits (Max positions, Max Drawdown)
            risk_status = self.position_manager.check_risk_limits()
            if not risk_status['can_open_new']:
                logger.warning(f"⛔ Risk Limit Rejection: {risk_status.get('reasons', [])}")
                return None

            # 3. Determine direction
            if signal_type == "BUY":
                direction = "LONG"
            elif signal_type == "SELL":
                direction = "SHORT"
            else:
                logger.error(f"Unknown signal type: {signal_type}")
                return None

            # 4. Calculate Volatility (Bandwidth)
            # Robustly try to find bandwidth, defaulting to 0.1% if data structure is missing
            try:
                # Expecting signal_data to contain 'entry_analysis' -> 'bb_analysis' -> 'bandwidth'
                bandwidth = signal_data['entry_analysis']['bb_analysis']['bandwidth']
            except (KeyError, TypeError):
                logger.warning("Volatility data missing in signal. Using default 0.001 (0.1%)")
                bandwidth = 0.001

            # Convert percentage bandwidth to price units
            price_volatility = bandwidth * current_price

            # 5. Calculate Stop Loss and Take Profit
            # Logic: SL = 1.5x Volatility, TP = 3.0x Volatility (Ensures 1:2 R:R)
            sl_dist = price_volatility * 1.5
            tp_dist = price_volatility * 3.0

            if direction == "LONG":
                stop_loss = current_price - sl_dist
                take_profit = current_price + tp_dist
            else: # SHORT
                stop_loss = current_price + sl_dist
                take_profit = current_price - tp_dist

            # 6. Calculate Position Size
            # Fetch current account balance for sizing
            portfolio = self.db.get_portfolio()
            account_balance = portfolio.get('balance', 1_000_000) # Default for safety
            
            # Use Risk Manager to calculate size based on Risk % (e.g., 2%)
            size = self.risk_manager.calculate_position_size(
                account_size=account_balance,
                risk_pct=self.risk_manager.max_risk_per_trade, 
                entry_price=current_price,
                stop_loss=stop_loss
            )

            # 7. Validate Trade (Check R:R ratios, invalid prices)
            validation = self.risk_manager.validate_trade(
                entry=current_price,
                stop=stop_loss,
                target=take_profit
            )

            if not validation['valid']:
                logger.warning(f"⛔ Trade Validation Failed: {validation.get('reason')}")
                return None

            # 8. Open Position in Database
            confidence = signal_data.get('confidence', 'LOW')
            # Extract reasons list and join string
            reasons_list = signal_data.get('reasons', [])
            notes = ", ".join(reasons_list) if isinstance(reasons_list, list) else str(reasons_list)
            
            position_id = self.db.open_position(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy="Multi-TF",
                confidence=confidence,
                notes=notes
            )

            if not position_id:
                logger.error(f"Failed to open position (Database error or duplicate): {symbol} {direction}")
                return None

            # 9. Update Portfolio and Return Summary
            # Force portfolio update to reflect margin/unrealized changes immediately
            self.position_manager._update_portfolio_unrealized()

            # Calculate metrics for the return summary
            metrics = self._calculate_risk_reward(current_price, stop_loss, take_profit, size, direction)

            summary = {
                'position_id': position_id,
                'symbol': symbol,
                'direction': direction,
                'entry_price': round(current_price, 2),
                'size': round(size, 4),
                'stop_loss': round(stop_loss, 2),
                'take_profit': round(take_profit, 2),
                'risk_amount': round(metrics['risk_amount'], 2),
                'reward_potential': round(metrics['reward_potential'], 2),
                'rr_ratio': round(metrics['rr_ratio'], 2),
                'confidence': confidence
            }

            logger.info(f"✅ EXECUTED {direction}: ID={position_id} @ {current_price:.2f} | Size={size:.4f} | R:R {summary['rr_ratio']}")
            return summary

        except Exception as e:
            logger.error(f"Error executing signal: {e}", exc_info=True)
            return None

    def get_execution_summary(self, position_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed summary of an executed position from the database.
        """
        try:
            pos = self.db.get_position(position_id)
            if not pos:
                logger.warning(f"Position ID {position_id} not found.")
                return None

            # Recalculate metrics for display
            metrics = self._calculate_risk_reward(
                entry=pos['entry_price'],
                stop_loss=pos['stop_loss'],
                take_profit=pos['take_profit'],
                size=pos['size'],
                direction=pos['direction']
            )

            return {
                'position_id': pos['id'],
                'symbol': pos['symbol'],
                'direction': pos['direction'],
                'entry_price': pos['entry_price'],
                'current_price': pos['current_price'],
                'stop_loss': pos['stop_loss'],
                'take_profit': pos['take_profit'],
                'size': pos['size'],
                'unrealized_pnl': pos['unrealized_pnl'],
                'risk_amount': metrics['risk_amount'],
                'reward_potential': metrics['reward_potential'],
                'rr_ratio': metrics['rr_ratio']
            }
        except Exception as e:
            logger.error(f"Error getting execution summary: {e}")
            return None

    def _calculate_risk_reward(self, entry: float, stop_loss: float, take_profit: float, size: float, direction: str) -> Dict[str, float]:
        """
        Helper to calculate risk and reward amounts based on direction.
        """
        if direction == "LONG":
            risk = (entry - stop_loss) * size
            reward = (take_profit - entry) * size
        else: # SHORT
            risk = (stop_loss - entry) * size
            reward = (entry - take_profit) * size

        # Handle edge cases (zero risk) to prevent division by zero
        if risk <= 0:
            rr_ratio = 0.0
        else:
            rr_ratio = reward / risk

        return {
            'risk_amount': abs(risk),
            'reward_potential': abs(reward),
            'rr_ratio': rr_ratio
        }


# --- TESTING SECTION ---
if __name__ == "__main__":
    print("🧪 STARTING TRADE EXECUTOR TEST...")
    
    # 1. Setup Test DB
    test_db_path = "../data/executor_test.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        
    # 2. Initialize Components
    db = TradingDatabase(test_db_path)
    risk_mgr = RiskManager(account_size=1_000_000, max_risk_per_trade=0.02)
    pos_mgr = PositionManager(db)
    executor = TradeExecutor(db, risk_mgr, pos_mgr)
    
    print("\n📝 Creating Mock Signal (BUY)...")
    # Mocking the structure from main bot
    # We include 'entry_analysis' to test volatility calculation
    signal = {
        'signal': 'BUY',
        'confidence': 'HIGH',
        'trend': {'direction': 'STRONG_BULL'},
        'entry_analysis': {
            'bb_analysis': {'bandwidth': 0.02} # 2% Bandwidth
        },
        'reasons': ['1h bullish', 'RSI oversold', 'MACD buy']
    }
    
    current_market_price = 4500.00
    
    # 3. Execute Signal
    print(f"🚀 Executing Signal at Price: {current_market_price}")
    result = executor.execute_signal(signal, current_price=current_market_price)
    
    if result:
        print("\n✅ Execution Successful:")
        print(f"   ID: {result['position_id']}")
        print(f"   Type: {result['direction']}")
        print(f"   Entry: ¥{result['entry_price']}")
        print(f"   SL:    ¥{result['stop_loss']}")
        print(f"   TP:    ¥{result['take_profit']}")
        print(f"   Size:  {result['size']:.4f}")
        print(f"   Risk:  ¥{result['risk_amount']:,.2f}")
        print(f"   R:R:   {result['rr_ratio']:.2f}")
        
        # 4. Verify Database State
        print("\n🔍 Verifying Database...")
        pos_summary = pos_mgr.get_position_summary()
        print(f"   Open Positions: {pos_summary['count']}")
        
        if pos_summary['count'] == 1:
            db_pos = pos_summary['positions'][0]
            print(f"   DB Symbol: {db_pos['symbol']}")
            print(f"   DB Unrealized PnL: {db_pos['unrealized_pnl']}")
            
    else:
        print("❌ Execution Failed")

    # 5. Test Missing Volatility (Robustness Check)
    print("\n📝 Testing Signal with Missing Volatility Data...")
    bad_signal = {'signal': 'SELL', 'confidence': 'LOW', 'reasons': ['Test']}
    res_bad = executor.execute_signal(bad_signal, current_price=4500.00)
    if res_bad:
        print(f"   ✅ Fallback Successful. SL: {res_bad['stop_loss']}")

    # 6. Cleanup
    db.close()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        
    print("\n✅ Trade Executor Test Complete!")