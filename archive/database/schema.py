"""
Database Schema Module - HYBRID VERSION
Combines Gemini's portfolio logic with Claude's trade history method.
"""

import sqlite3
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TradingDatabase:
    """
    A robust SQLite wrapper for managing trading data.
    Handles portfolio, positions, trades, and performance tracking.
    """

    def __init__(self, db_path: str = "data/trading.db"):
        """
        Initialize database connection and create tables.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        
        # Ensure data directory exists
        try:
            db_dir = os.path.dirname(db_path)
            if db_dir:
                Path(db_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.critical(f"Failed to create directory {db_dir}: {e}")
            raise

        self.conn = None
        self._connect()
        self._create_tables()
        self._initialize_portfolio()

    def _connect(self):
        """Establish SQLite connection with Row factory."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            logger.info(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            logger.critical(f"Database connection failed: {e}")
            raise

    def _create_tables(self):
        """Create all required tables if they don't exist."""
        try:
            cursor = self.conn.cursor()
            
            # Portfolio table - historical snapshots
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    margin_used REAL DEFAULT 0,
                    free_margin REAL NOT NULL,
                    unrealized_pnl REAL DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0
                )
            """)

            # Positions table - currently open trades
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    open_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    size REAL NOT NULL,
                    unrealized_pnl REAL DEFAULT 0,
                    strategy TEXT,
                    confidence TEXT,
                    notes TEXT,
                    UNIQUE(symbol, direction)
                )
            """)

            # Trades table - closed trade history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    open_time DATETIME NOT NULL,
                    close_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    size REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_percent REAL NOT NULL,
                    commission REAL DEFAULT 0,
                    exit_reason TEXT,
                    strategy TEXT,
                    notes TEXT
                )
            """)
            
            # Performance table - daily metrics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE UNIQUE NOT NULL,
                    starting_balance REAL NOT NULL,
                    ending_balance REAL NOT NULL,
                    daily_pnl REAL NOT NULL,
                    daily_pnl_percent REAL NOT NULL,
                    trades_count INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    largest_win REAL DEFAULT 0,
                    largest_loss REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0
                )
            """)
            
            self.conn.commit()
            logger.info("Database tables created successfully")
            
        except sqlite3.Error as e:
            logger.critical(f"Failed to create tables: {e}")
            raise

    def _initialize_portfolio(self, initial_balance: float = 1_000_000.0):
        """
        Initialize portfolio with starting balance if empty.
        
        Args:
            initial_balance: Starting account balance (default ¥1,000,000)
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM portfolio")
            count = cursor.fetchone()[0]
            
            if count == 0:
                logger.info(f"Initializing portfolio with ¥{initial_balance:,.0f}")
                cursor.execute("""
                    INSERT INTO portfolio (
                        balance, equity, margin_used, free_margin, 
                        unrealized_pnl, realized_pnl, 
                        total_trades, winning_trades, losing_trades
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    initial_balance, initial_balance, 0.0, initial_balance,
                    0.0, 0.0, 0, 0, 0
                ))
                self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize portfolio: {e}")

    def get_portfolio(self) -> Dict[str, Any]:
        """
        Get current portfolio state.
        
        Returns:
            Dictionary with portfolio data or empty dict on error
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM portfolio ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else {}
        except sqlite3.Error as e:
            logger.error(f"Failed to get portfolio: {e}")
            return {}

    def update_portfolio(self, **kwargs) -> bool:
        """
        Update portfolio values and create new snapshot.
        
        Args:
            **kwargs: Fields to update (balance, equity, margin_used, etc.)
            
        Returns:
            True on success, False on error
        """
        try:
            current = self.get_portfolio()
            if not current:
                return False
            
            # Update provided values
            for key, value in kwargs.items():
                if key in current:
                    current[key] = value
            
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio (
                    balance, equity, margin_used, free_margin, 
                    unrealized_pnl, realized_pnl, 
                    total_trades, winning_trades, losing_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                current['balance'], current['equity'], current['margin_used'], 
                current['free_margin'], current['unrealized_pnl'], current['realized_pnl'],
                current['total_trades'], current['winning_trades'], current['losing_trades']
            ))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to update portfolio: {e}")
            return False

    def open_position(self, symbol: str, direction: str, entry_price: float, size: float, 
                      stop_loss: Optional[float] = None, take_profit: Optional[float] = None, 
                      strategy: Optional[str] = None, confidence: Optional[str] = None, 
                      notes: Optional[str] = None) -> Optional[int]:
        """
        Open a new position.
        
        Args:
            symbol: Trading symbol (e.g., "XAU_JPY")
            direction: "LONG" or "SHORT"
            entry_price: Entry price
            size: Position size in units
            stop_loss: Stop loss price (optional)
            take_profit: Take profit price (optional)
            strategy: Strategy name (optional)
            confidence: Signal confidence (optional)
            notes: Additional notes (optional)
            
        Returns:
            Position ID on success, None if duplicate or error
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO positions (
                    open_time, symbol, direction, entry_price, current_price,
                    stop_loss, take_profit, size, unrealized_pnl,
                    strategy, confidence, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(), symbol, direction, entry_price, entry_price,
                stop_loss, take_profit, size, 0.0,
                strategy, confidence, notes
            ))
            self.conn.commit()
            position_id = cursor.lastrowid
            logger.info(f"Position opened: {direction} {size} {symbol} @ {entry_price}")
            return position_id
        except sqlite3.IntegrityError:
            logger.warning(f"Position already exists for {symbol} {direction}")
            return None
        except sqlite3.Error as e:
            logger.error(f"Failed to open position: {e}")
            return None

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions.
        
        Returns:
            List of position dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM positions")
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Failed to get open positions: {e}")
            return []

    def get_position(self, position_id: int) -> Optional[Dict[str, Any]]:
        """
        Get specific position by ID.
        
        Args:
            position_id: Position ID
            
        Returns:
            Position dictionary or None if not found
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to get position {position_id}: {e}")
            return None

    def update_position_price(self, position_id: int, current_price: float) -> bool:
        """
        Update position's current price and unrealized P&L.
        
        Args:
            position_id: Position ID
            current_price: Current market price
            
        Returns:
            True on success, False on error
        """
        try:
            pos = self.get_position(position_id)
            if not pos:
                return False
            
            # Calculate unrealized P&L
            diff = current_price - pos['entry_price']
            if pos['direction'] == 'SHORT':
                diff = -diff
                
            unrealized_pnl = diff * pos['size']
            
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE positions 
                SET current_price = ?, unrealized_pnl = ? 
                WHERE id = ?
            """, (current_price, unrealized_pnl, position_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to update position price: {e}")
            return False

    def close_position(self, position_id: int, exit_price: float, 
                       exit_reason: str = "Manual") -> Optional[Dict[str, Any]]:
        """
        Close a position and update portfolio correctly.
        CRITICAL: Recalculates unrealized P&L from remaining positions.
        
        Args:
            position_id: Position ID to close
            exit_price: Exit price
            exit_reason: Reason for exit (e.g., "Stop Loss", "Take Profit")
            
        Returns:
            Dictionary with pnl, pnl_percent, exit_reason or None on error
        """
        try:
            pos = self.get_position(position_id)
            if not pos:
                return None
            
            # 1. Calculate P&L for this specific trade
            diff = exit_price - pos['entry_price']
            if pos['direction'] == 'SHORT':
                diff = -diff
            
            pnl = diff * pos['size']
            invested = pos['entry_price'] * pos['size']
            pnl_percent = (pnl / invested * 100) if invested != 0 else 0.0
            
            cursor = self.conn.cursor()
            
            # 2. Archive to Trades History
            cursor.execute("""
                INSERT INTO trades (
                    open_time, close_time, symbol, direction,
                    entry_price, exit_price, stop_loss, take_profit,
                    size, pnl, pnl_percent, exit_reason, strategy, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pos['open_time'], datetime.now(), pos['symbol'], pos['direction'],
                pos['entry_price'], exit_price, pos['stop_loss'], pos['take_profit'],
                pos['size'], pnl, pnl_percent, exit_reason, pos['strategy'], pos['notes']
            ))
            
            # 3. Delete from Active Positions
            cursor.execute("DELETE FROM positions WHERE id = ?", (position_id,))
            
            # 4. CRITICAL FIX: Recalculate Portfolio from REMAINING positions
            cursor.execute("SELECT SUM(unrealized_pnl) FROM positions")
            result = cursor.fetchone()[0]
            remaining_unrealized_pnl = result if result is not None else 0.0
            
            # 5. Update Portfolio Snapshot
            port = self.get_portfolio()
            new_balance = port['balance'] + pnl
            new_equity = new_balance + remaining_unrealized_pnl
            
            total_trades = port['total_trades'] + 1
            win_trades = port['winning_trades'] + (1 if pnl > 0 else 0)
            loss_trades = port['losing_trades'] + (1 if pnl <= 0 else 0)
            
            cursor.execute("""
                INSERT INTO portfolio (
                    balance, equity, margin_used, free_margin, 
                    unrealized_pnl, realized_pnl, 
                    total_trades, winning_trades, losing_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_balance, 
                new_equity,
                port['margin_used'],
                new_equity - port['margin_used'], 
                remaining_unrealized_pnl,
                port['realized_pnl'] + pnl,
                total_trades, win_trades, loss_trades
            ))
            
            self.conn.commit()
            logger.info(f"Closed position #{position_id}: P&L ¥{pnl:,.2f}")
            
            return {
                'pnl': pnl, 
                'pnl_percent': pnl_percent, 
                'exit_reason': exit_reason
            }
            
        except sqlite3.Error as e:
            logger.error(f"Failed to close position: {e}")
            self.conn.rollback()
            return None

    def get_trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent trade history.
        
        Args:
            limit: Maximum number of trades to return
            
        Returns:
            List of trade dictionaries, newest first
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                ORDER BY close_time DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Failed to get trade history: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """
        Calculate comprehensive trading statistics.
        
        Returns:
            Dictionary with statistics or empty dict on error
        """
        try:
            cursor = self.conn.cursor()
            stats = {}
            
            # Basic statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    MAX(pnl) as largest_win,
                    MIN(pnl) as largest_loss
                FROM trades
            """)
            stats.update(dict(cursor.fetchone()))
            
            # Win rate
            if stats['total_trades'] > 0:
                stats['win_rate'] = (stats['winning_trades'] / stats['total_trades']) * 100
            else:
                stats['win_rate'] = 0.0
            
            # Profit factor
            cursor.execute("SELECT SUM(pnl) FROM trades WHERE pnl > 0")
            gross_profit = cursor.fetchone()[0] or 0.0
            
            cursor.execute("SELECT ABS(SUM(pnl)) FROM trades WHERE pnl < 0")
            gross_loss = cursor.fetchone()[0] or 0.0
            
            stats['profit_factor'] = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
            
            # Average win/loss
            cursor.execute("SELECT AVG(pnl) FROM trades WHERE pnl > 0")
            stats['avg_win'] = cursor.fetchone()[0] or 0.0
            
            cursor.execute("SELECT AVG(pnl) FROM trades WHERE pnl < 0")
            stats['avg_loss'] = cursor.fetchone()[0] or 0.0
            
            return stats
        except sqlite3.Error as e:
            logger.error(f"Failed to calculate statistics: {e}")
            return {}

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")


# --- TESTING ---
if __name__ == "__main__":
    print("🧪 Testing HYBRID Database System...")
    
    test_db = "../data/trading_test.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    db = TradingDatabase(test_db)
    
    print("\n💰 Initial Portfolio:")
    port = db.get_portfolio()
    print(f"   Balance: ¥{port['balance']:,.0f}")
    print(f"   Equity:  ¥{port['equity']:,.0f}")
    
    print("\n📊 Opening 2 positions...")
    # Position 1 - Will close with profit
    id1 = db.open_position("XAU_JPY", "LONG", 4500.00, 1.0, 
                           stop_loss=4450.00, take_profit=4600.00,
                           strategy="Multi-TF", confidence="HIGH")
    
    # Position 2 - Will remain open
    id2 = db.open_position("USD_JPY", "LONG", 150.00, 100.0,
                           stop_loss=149.00, take_profit=152.00,
                           strategy="Multi-TF", confidence="MODERATE")
    
    print(f"   Position 1 ID: {id1}")
    print(f"   Position 2 ID: {id2}")
    
    print("\n📈 Updating prices...")
    db.update_position_price(id1, 4600.00)  # +100 PnL
    db.update_position_price(id2, 151.00)   # +100 PnL
    
    positions = db.get_open_positions()
    print(f"   Position 1 Unrealized: ¥{positions[0]['unrealized_pnl']:,.2f}")
    print(f"   Position 2 Unrealized: ¥{positions[1]['unrealized_pnl']:,.2f}")
    
    print("\n🔒 Closing Position 1 (Take Profit)...")
    trade = db.close_position(id1, 4600.00, "Take Profit")
    print(f"   P&L: ¥{trade['pnl']:,.2f} ({trade['pnl_percent']:.2f}%)")
    
    print("\n💰 Portfolio After Close:")
    port = db.get_portfolio()
    print(f"   Balance:     ¥{port['balance']:,.0f} (Expected: ¥1,000,100)")
    print(f"   Unrealized:  ¥{port['unrealized_pnl']:,.0f} (Expected: ¥100 from Pos2)")
    print(f"   Equity:      ¥{port['equity']:,.0f} (Expected: ¥1,000,200)")
    print(f"   Total Trades: {port['total_trades']}")
    print(f"   Win Rate:     {port['winning_trades']}/{port['total_trades']}")
    
    print("\n📊 Statistics:")
    stats = db.get_statistics()
    print(f"   Total Trades: {stats['total_trades']}")
    print(f"   Win Rate:     {stats['win_rate']:.1f}%")
    print(f"   Total P&L:    ¥{stats['total_pnl']:,.2f}")
    print(f"   Profit Factor: {stats['profit_factor']:.2f}")
    
    print("\n📜 Trade History:")
    trades = db.get_trade_history(limit=5)
    for t in trades:
        print(f"   {t['symbol']} {t['direction']} | P&L: ¥{t['pnl']:,.2f}")
    
    db.close()
    
    # Cleanup
    if os.path.exists(test_db):
        os.remove(test_db)
    
    print("\n✅ HYBRID Database Test Complete!")