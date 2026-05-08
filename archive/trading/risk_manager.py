import logging
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RiskManager:
    """
    A comprehensive Risk Management system for trading.
    
    This class handles:
    - Position sizing based on account balance and risk percentage.
    - Trade validation (Risk/Reward ratios).
    - Stop Loss and Take Profit calculations.
    - Portfolio-level risk limits (Daily loss, Max positions).
    """

    def __init__(
        self, 
        account_size: float = 1_000_000.0, 
        max_risk_per_trade: float = 0.02, 
        max_daily_loss: float = 0.05, 
        max_positions: int = 3
    ):
        """
        Initialize the Risk Manager.

        Args:
            account_size (float): Total trading capital (e.g., ¥1,000,000).
            max_risk_per_trade (float): Max risk per individual trade (default 2% or 0.02).
            max_daily_loss (float): Max total loss allowed per day (default 5% or 0.05).
            max_positions (int): Maximum number of concurrent open trades.
        """
        self.account_size = account_size
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_positions = max_positions
        
        # Internal tracking
        self.current_daily_loss = 0.0
        self.peak_equity = account_size

    def calculate_position_size(
        self, 
        account_size: float, 
        risk_pct: float, 
        entry_price: float, 
        stop_loss: float
    ) -> float:
        """
        Calculate the appropriate position size (units).
        
        Formula: (Account * Risk%) / |Entry - StopLoss|

        Args:
            account_size: Current account balance.
            risk_pct: Risk per trade (e.g., 0.01 for 1%).
            entry_price: Planned entry price.
            stop_loss: Planned stop loss price.

        Returns:
            float: Number of units (e.g., ounces of gold) to buy/sell.
        """
        if risk_pct > self.max_risk_per_trade:
            logger.warning(f"Requested risk {risk_pct:.1%} exceeds limit {self.max_risk_per_trade:.1%}. Capping to limit.")
            risk_pct = self.max_risk_per_trade

        if entry_price <= 0 or stop_loss <= 0:
            logger.error("Invalid prices: Entry and Stop must be positive.")
            return 0.0

        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share == 0:
            logger.error("Invalid Stop Loss: Equal to Entry Price.")
            return 0.0

        risk_amount = account_size * risk_pct
        position_size = risk_amount / risk_per_share
        
        logger.info(f"Calc Size: Risk ¥{risk_amount:,.0f} / Dist ¥{risk_per_share:.2f} = {position_size:.4f} units")
        return position_size

    def validate_trade(
        self, 
        entry: float, 
        stop: float, 
        target: float, 
        min_rr: float = 2.0
    ) -> Dict[str, Any]:
        """
        Validate if a trade meets risk/reward requirements.

        Returns:
            Dict: {'valid': bool, 'reason': str, 'rr_ratio': float, ...}
        """
        if entry <= 0 or stop <= 0 or target <= 0:
            return {'valid': False, 'reason': "Invalid price inputs (<= 0)."}

        # Determine direction
        is_long = target > entry
        
        if is_long and stop >= entry:
            return {'valid': False, 'reason': "Long trade: Stop must be below Entry."}
        if not is_long and stop <= entry:
            return {'valid': False, 'reason': "Short trade: Stop must be above Entry."}

        # Calculate R:R
        risk_dist = abs(entry - stop)
        reward_dist = abs(target - entry)
        
        if risk_dist == 0:
            return {'valid': False, 'reason': "Zero risk distance (Entry == Stop)."}

        rr_ratio = reward_dist / risk_dist

        valid = rr_ratio >= min_rr
        reason = "Approved" if valid else f"R:R {rr_ratio:.2f} < Min {min_rr:.1f}"

        return {
            'valid': valid,
            'reason': reason,
            'rr_ratio': round(rr_ratio, 2),
            'risk_amount': risk_dist,
            'reward_amount': reward_dist
        }

    def calculate_stop_loss(self, entry: float, stop_pct: float, direction: str = 'LONG') -> float:
        """
        Calculate Stop Loss price based on percentage.
        """
        if direction.upper() == 'LONG':
            return entry * (1 - stop_pct)
        else:
            return entry * (1 + stop_pct)

    def calculate_take_profit(self, entry: float, stop: float, rr_ratio: float = 2.0) -> float:
        """
        Calculate Take Profit price based on Risk/Reward ratio.
        """
        risk = abs(entry - stop)
        reward = risk * rr_ratio
        
        if entry > stop: # Long
            return entry + reward
        else: # Short
            return entry - reward

    def check_risk_limits(
        self, 
        current_positions: int, 
        daily_realized_loss: float
    ) -> Dict[str, Any]:
        """
        Check if portfolio limits (Daily Loss, Max Positions) are breached.
        """
        # 1. Check Max Positions
        if current_positions >= self.max_positions:
            return {
                'allowed': False,
                'reason': f"Max positions reached ({current_positions}/{self.max_positions})"
            }

        # 2. Check Daily Loss Limit
        max_loss_amount = self.account_size * self.max_daily_loss
        if daily_realized_loss >= max_loss_amount:
            return {
                'allowed': False,
                'reason': f"Daily loss limit hit (¥{daily_realized_loss:,.0f} >= ¥{max_loss_amount:,.0f})"
            }

        return {'allowed': True, 'reason': "Within limits"}

    def kelly_criterion(self, win_rate: float, reward_risk_ratio: float) -> float:
        """
        Calculate Kelly Criterion percentage (Optional optimal sizing).
        Formula: K% = W - [(1 - W) / R]
        """
        if reward_risk_ratio <= 0: return 0.0
        kelly = win_rate - ((1 - win_rate) / reward_risk_ratio)
        return max(0.0, kelly)  # Ensure non-negative

    def update_drawdown(self, current_equity: float) -> float:
        """
        Update peak equity and return current drawdown percentage.
        """
        self.peak_equity = max(self.peak_equity, current_equity)
        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        return drawdown

# --- Example Usage ---
if __name__ == "__main__":
    print("--- Risk Manager Test ---")
    
    # 1. Initialize
    risk_mgr = RiskManager(
        account_size=1_000_000, # ¥1M Account
        max_risk_per_trade=0.02, # 2% per trade
        max_positions=3
    )

    # 2. Setup Trade Scenarios
    entry_price = 700_000 # Gold Price (¥/oz approx)
    stop_loss = 693_000   # 1% risk distance
    target_price = 714_000 # 2% reward distance
    
    # 3. Calculate Position Size
    print(f"\nAccount: ¥1,000,000 | Risk: 2% | Entry: {entry_price}")
    size = risk_mgr.calculate_position_size(
        account_size=1_000_000,
        risk_pct=0.02,
        entry_price=entry_price,
        stop_loss=stop_loss
    )
    print(f"Recommended Position Size: {size:.4f} units")

    # 4. Validate Trade
    validation = risk_mgr.validate_trade(entry_price, stop_loss, target_price)
    
    if validation['valid']:
        print(f"✅ Trade Validated! R:R = {validation['rr_ratio']}:1")
    else:
        print(f"❌ Trade Rejected: {validation['reason']}")

    # 5. Check Limits
    status = risk_mgr.check_risk_limits(current_positions=2, daily_realized_loss=10000)
    print(f"\nRisk Check: {status['reason']}")