"""Quick script to check trading data"""
from database.schema import TradingDatabase

# Connect
db = TradingDatabase("data/trading.db")

# Get portfolio
portfolio = db.get_portfolio()
print("\n💰 PORTFOLIO:")
print(f"Balance: ¥{portfolio['balance']:,.2f}")
print(f"Equity: ¥{portfolio['equity']:,.2f}")
print(f"Unrealized P&L: ¥{portfolio['unrealized_pnl']:,.2f}")
print(f"Realized P&L: ¥{portfolio['realized_pnl']:,.2f}")

# Get trades
trades = db.get_trade_history(limit=10)
print(f"\n📈 CLOSED TRADES: {len(trades)}")
for trade in trades:
    print(f"  #{trade['id']}: {trade['direction']} @ {trade['entry_price']:.2f} → {trade['exit_price']:.2f} | P&L: ¥{trade['pnl']:,.2f}")

# Get positions
positions = db.get_open_positions()
print(f"\n📊 OPEN POSITIONS: {len(positions)}")
for pos in positions:
    print(f"  #{pos['id']}: {pos['direction']} {pos['symbol']} @ {pos['entry_price']:.2f} | P&L: ¥{pos['unrealized_pnl']:,.2f}")

# Get stats
stats = db.get_statistics()
print("\n📊 STATISTICS:")
print(f"Total Trades: {stats['total_trades']}")
print(f"Win Rate: {stats['win_rate']:.1f}%")
print(f"Total P&L: ¥{stats.get('total_pnl', 0):,.2f}")

db.close()
print("\n✅ Done!")
