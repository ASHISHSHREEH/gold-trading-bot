import sqlite3
conn = sqlite3.connect(r'D:\My Projects\gold-trading-bot\data\trading_mt5.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('Tables:', tables)
for t in tables:
    c.execute(f'SELECT COUNT(*) FROM {t[0]}')
    print(f'  {t[0]}: {c.fetchone()[0]} rows')
c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 5")
print('Last 5 trades:')
for r in c.fetchall():
    print(' ', r)
conn.close()
