"""
check_data.py — quick MT5 account + trade history snapshot.
Run: python check_data.py
MT5 terminal must be open and logged in.
"""
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 not installed. Run: pip install MetaTrader5")
    sys.exit(1)


def line(char="─", w=60):
    print(char * w)


def connect():
    # Try auto-connect first (works when MT5 is already open and logged in)
    if mt5.initialize():
        return

    # Fallback: explicit credentials
    path     = os.getenv("MT5_PATH", "")
    login    = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")
    ok = mt5.initialize(
        path     = path if path else None,
        login    = login if login else None,
        password = password if password else None,
        server   = server if server else None,
    )
    if not ok:
        print(f"MT5 connection failed: {mt5.last_error()}")
        print("Make sure MetaTrader5 terminal is open and logged in.")
        sys.exit(1)


def show_account():
    a = mt5.account_info()
    if a is None:
        print("Could not read account info.")
        return

    line("═")
    print("  ACCOUNT")
    line("═")
    print(f"  Name         : {a.name}")
    print(f"  Login        : {a.login}")
    print(f"  Server       : {a.server}")
    print(f"  Currency     : {a.currency}")
    print(f"  Leverage     : 1:{a.leverage}")
    line()
    print(f"  Balance      : {a.balance:>12,.2f} {a.currency}")
    print(f"  Equity       : {a.equity:>12,.2f} {a.currency}")
    print(f"  Floating P&L : {a.profit:>+12,.2f} {a.currency}")
    print(f"  Margin used  : {a.margin:>12,.2f} {a.currency}")
    print(f"  Free margin  : {a.margin_free:>12,.2f} {a.currency}")
    ml = a.margin_level
    ml_str = f"{ml:.1f}%" if ml > 0 else "N/A"
    print(f"  Margin level : {ml_str:>12}")
    line()


def show_open_positions():
    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        print("  Open Positions : none")
        line()
        return

    print(f"  OPEN POSITIONS ({len(positions)})")
    line()
    for p in positions:
        direction = "BUY " if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        print(
            f"  {p.symbol:<16} {direction}  "
            f"vol={p.volume}  entry={p.price_open:.5f}  "
            f"current={p.price_current:.5f}  "
            f"P&L={p.profit:+.2f}  SL={p.sl:.5f}  TP={p.tp:.5f}"
        )
    line()


def show_trade_history(limit=10):
    from datetime import timezone, timedelta
    now  = datetime.now(timezone.utc)
    from_dt = now - timedelta(days=30)
    deals = mt5.history_deals_get(from_dt, now)

    if deals is None or len(deals) == 0:
        print("  Trade History  : no deals in last 30 days")
        line()
        return

    # Only closing deals
    closing = [
        d for d in deals
        if hasattr(mt5, "DEAL_ENTRY_OUT") and d.entry == mt5.DEAL_ENTRY_OUT
    ]

    print(f"  RECENT CLOSED TRADES (last 30 days, showing {min(limit, len(closing))})")
    line()
    total_profit = 0.0
    wins = 0
    for d in closing[-limit:]:
        ts     = datetime.fromtimestamp(d.time).strftime("%m-%d %H:%M")
        result = "WIN " if d.profit > 0 else "LOSS"
        print(
            f"  {ts}  {d.symbol:<14} {result}  "
            f"vol={d.volume}  @ {d.price:.5f}  "
            f"P&L={d.profit:>+8.2f}"
        )
        total_profit += d.profit
        if d.profit > 0:
            wins += 1

    line()
    total = len(closing)
    win_rate = (wins / total * 100) if total > 0 else 0.0
    print(f"  Total deals    : {total}")
    print(f"  Win rate       : {win_rate:.1f}%  ({wins}/{total})")
    print(f"  Total P&L      : {total_profit:+.2f}")
    line()


def show_bot_stats():
    """Read bot's own SQLite trade log if it exists."""
    db_path = "data/trading_mt5.db"
    if not os.path.exists(db_path):
        return

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.execute("""
        SELECT
            COUNT(*)                                     AS total,
            SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(profit)                                  AS net_pnl,
            AVG(CASE WHEN profit > 0 THEN profit END)    AS avg_win,
            AVG(CASE WHEN profit < 0 THEN profit END)    AS avg_loss,
            MAX(profit)                                  AS best,
            MIN(profit)                                  AS worst
        FROM trades WHERE close_time IS NOT NULL
    """)
    row = dict(cur.fetchone())
    conn.close()

    if not row["total"]:
        return

    total = row["total"] or 0
    wins  = row["wins"]  or 0
    wr    = (wins / total * 100) if total > 0 else 0
    avg_w = row["avg_win"]  or 0
    avg_l = row["avg_loss"] or 0
    pf    = (abs(avg_w) * wins) / (abs(avg_l) * (total - wins)) if avg_l and (total - wins) > 0 else 0

    print("  BOT TRADE LOG (SQLite)")
    line()
    print(f"  Closed trades  : {total}")
    print(f"  Win rate       : {wr:.1f}%  ({wins}/{total})")
    print(f"  Net P&L        : {row['net_pnl']:+.2f}")
    print(f"  Avg win        : {avg_w:+.2f}")
    print(f"  Avg loss       : {avg_l:+.2f}")
    print(f"  Profit factor  : {pf:.2f}")
    print(f"  Best trade     : {row['best']:+.2f}")
    print(f"  Worst trade    : {row['worst']:+.2f}")
    line()


if __name__ == "__main__":
    print()
    print(f"  MT5 Account Check — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    connect()
    show_account()
    show_open_positions()
    show_trade_history(limit=10)
    show_bot_stats()
    mt5.shutdown()
    print("  Done.")
    print()
