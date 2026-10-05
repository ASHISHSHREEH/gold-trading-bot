import sqlite3
conn = sqlite3.connect(r'D:\My Projects\gold-trading-bot\data\trading_mt5.db')
c = conn.cursor()
c.execute('PRAGMA table_info(trades)')
print('Trades columns:')
for r in c.fetchall():
    print(' ', r)
print()
c.execute('SELECT * FROM trades ORDER BY id')
print('All trades:')
for r in c.fetchall():
    print(' ', r)
conn.close()
