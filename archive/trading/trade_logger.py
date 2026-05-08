"""
Trade Logger Module
Handles persistent logging of trade signals to CSV for analysis and tracking.
"""

import os
import csv
import logging
import pandas as pd
from typing import Dict, Any

# Configure logging for this module
logger = logging.getLogger(__name__)

class TradeLogger:
    """
    Logs trading activity to a CSV file and provides summary statistics.
    """
    
    def __init__(self, log_dir: str = "logs", filename: str = "trade_history.csv"):
        """
        Initialize the trade logger.
        
        Args:
            log_dir (str): Directory to store logs.
            filename (str): Name of the CSV file.
        """
        self.log_dir = log_dir
        self.filename = filename
        self.filepath = os.path.join(log_dir, filename)
        
        # Define standard columns for consistency
        self.columns = [
            "timestamp", "signal", "confidence", "direction", 
            "entry", "stop_loss", "take_profit", "size", 
            "risk_amount", "reward_potential", "rr_ratio", 
            "trend", "reason"
        ]
        
        self._initialize_log_file()

    def _initialize_log_file(self):
        """Creates the directory and CSV file with headers if they don't exist."""
        try:
            # BUG FIX: exist_ok=True prevents crash if dir exists
            if not os.path.exists(self.log_dir):
                os.makedirs(self.log_dir, exist_ok=True)
                logger.info(f"Created log directory: {self.log_dir}")
                
            if not os.path.exists(self.filepath):
                with open(self.filepath, mode='w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.columns)
                logger.info(f"Created trade log file: {self.filepath}")
                
        except OSError as e:
            logger.error(f"Failed to initialize trade logger: {e}")

    def log_trade(self, trade_dict: Dict[str, Any]) -> bool:
        """
        Appends a new trade record to the CSV file.
        """
        try:
            # Ensure all columns exist, fill missing with None
            row_data = [trade_dict.get(col) for col in self.columns]
            
            with open(self.filepath, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row_data)
                
            logger.info(f"Trade logged successfully: {trade_dict.get('signal')} {trade_dict.get('direction')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
            return False

    def get_recent_trades(self, n: int = 5) -> pd.DataFrame:
        """Retrieves the last N trades from the log."""
        try:
            if not os.path.exists(self.filepath):
                return pd.DataFrame(columns=self.columns)
                
            df = pd.read_csv(self.filepath)
            return df.tail(n)
            
        except Exception as e:
            logger.error(f"Failed to read trade log: {e}")
            return pd.DataFrame(columns=self.columns)

    def get_trade_summary(self) -> Dict[str, Any]:
        """Calculates summary statistics from the trade log."""
        try:
            if not os.path.exists(self.filepath):
                return {"total_trades": 0, "message": "No log file found"}
                
            df = pd.read_csv(self.filepath)
            
            if df.empty:
                return {"total_trades": 0, "message": "Log file is empty"}
                
            summary = {
                "total_trades": len(df),
                "buy_count": len(df[df['direction'] == 'LONG']),
                "sell_count": len(df[df['direction'] == 'SHORT']),
                "avg_rr_ratio": df['rr_ratio'].mean(),
                "last_trade_time": df['timestamp'].iloc[-1]
            }
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return {}