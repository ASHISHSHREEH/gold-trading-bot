"""
Read-only monitoring dashboard for the gold trading bot.
Reads from data/trading_mt5.db — no MT5 connection required.

Usage:
    python dashboard.py
    Open http://localhost:5000 in a browser or phone (use LAN IP on phone)
"""
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string

DB_PATH = Path(__file__).parent / "data" / "trading_mt5.db"

app = Flask(__name__)


# ── DB helpers (read-only) ─────────────────────────────────────────────────────

def _open():
    if not DB_PATH.exists():
        return None
    uri = DB_PATH.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _q(sql, params=()):
    conn = _open()
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _q1(sql, params=()):
    conn = _open()
    if conn is None:
        return {}
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


# ── API ────────────────────────────────────────────────────────────────────────

@app.route("/api/data")
def api_data():
    db_exists = DB_PATH.exists()

    session     = _q1("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
    bot_running = bool(session and session.get("end_time") is None)

    # Estimated balance (DB-only; excludes unrealized P&L on open positions)
    if session:
        if bot_running:
            closed_profit = _q1(
                "SELECT COALESCE(SUM(profit), 0) AS s FROM trades "
                "WHERE session_id=? AND close_time IS NOT NULL AND profit IS NOT NULL",
                (session["id"],),
            ).get("s") or 0
            balance = (session.get("start_balance") or 0) + closed_profit
        else:
            balance = session.get("end_balance") or session.get("start_balance") or 0
    else:
        balance = 0

    # All-time closed-trade stats
    st = _q1("""
        SELECT COUNT(*)                                       AS total,
               SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END)  AS wins,
               COALESCE(SUM(profit), 0)                      AS total_profit,
               COALESCE(MAX(profit), 0)                      AS best_trade,
               COALESCE(MIN(profit), 0)                      AS worst_trade
          FROM trades
         WHERE close_time IS NOT NULL AND profit IS NOT NULL
    """)
    total        = st.get("total") or 0
    wins         = st.get("wins") or 0
    win_rate     = round(wins / total * 100, 1) if total else 0.0
    total_profit = st.get("total_profit") or 0

    # Today's P&L
    today = date.today().isoformat()
    daily_pnl = _q1(
        "SELECT COALESCE(SUM(profit), 0) AS d FROM trades "
        "WHERE date(close_time) = ? AND profit IS NOT NULL",
        (today,),
    ).get("d") or 0

    # Symbols seen across all trades
    symbols = [r["symbol"] for r in _q("SELECT DISTINCT symbol FROM trades ORDER BY symbol")]

    # Open positions (DB records with no close_time)
    open_positions = _q("""
        SELECT ticket, symbol, direction, open_time,
               entry_price, volume, stop_loss, take_profit
          FROM trades
         WHERE close_time IS NULL
         ORDER BY open_time DESC
    """)

    # Last 20 closed trades
    recent_trades = _q("""
        SELECT ticket, symbol, direction, open_time, close_time,
               entry_price, exit_price, profit, exit_reason, rr_ratio
          FROM trades
         WHERE close_time IS NOT NULL
         ORDER BY close_time DESC
         LIMIT 20
    """)

    last_signal = _q1("SELECT MAX(timestamp) AS ts FROM signals").get("ts")

    return jsonify(
        db_exists      = db_exists,
        bot_running    = bot_running,
        session_start  = session.get("start_time") if session else None,
        balance        = round(float(balance), 2),
        win_rate       = win_rate,
        total_trades   = total,
        winning_trades = wins,
        total_profit   = round(float(total_profit), 2),
        daily_pnl      = round(float(daily_pnl), 2),
        best_trade     = round(float(st.get("best_trade") or 0), 2),
        worst_trade    = round(float(st.get("worst_trade") or 0), 2),
        symbols        = symbols,
        open_positions = open_positions,
        recent_trades  = recent_trades,
        last_signal    = last_signal,
        refreshed_at   = datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    )


# ── HTML ───────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Bot Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0d0d;--card:#161616;--border:#232323;
  --gold:#f5a623;--text:#ddd;--dim:#5a5a5a;
  --green:#22c55e;--red:#ef4444
}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:14px;min-height:100vh;padding-bottom:2.5rem}
#prog{height:2px;background:var(--gold);width:100%;transition:width 30s linear}
header{
  background:#111;border-bottom:1px solid var(--border);
  padding:.75rem 1rem;display:flex;align-items:center;
  justify-content:space-between;position:sticky;top:0;z-index:99
}
header h1{font-size:.95rem;font-weight:700;color:var(--gold);letter-spacing:.4px}
.badge{
  display:inline-flex;align-items:center;gap:.35rem;
  padding:.22rem .6rem;border-radius:100px;font-size:.68rem;
  font-weight:600;text-transform:uppercase;letter-spacing:.5px
}
.badge.run{background:rgba(34,197,94,.12);color:var(--green);border:1px solid rgba(34,197,94,.22)}
.badge.stop{background:rgba(239,68,68,.1);color:var(--red);border:1px solid rgba(239,68,68,.18)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor}
.pulse{animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}

main{max-width:1100px;margin:0 auto;padding:.75rem}

/* 2-col on mobile, 4-col on wider */
.grid4{display:grid;grid-template-columns:repeat(2,1fr);gap:.6rem;margin-bottom:.6rem}
@media(min-width:580px){.grid4{grid-template-columns:repeat(4,1fr)}}

.stat{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.85rem}
.stat .lbl{font-size:.62rem;text-transform:uppercase;letter-spacing:.8px;color:var(--dim);margin-bottom:.4rem}
.stat .val{font-size:1.4rem;font-weight:700;line-height:1}
.stat .sub{font-size:.62rem;color:var(--dim);margin-top:.3rem}

.pos{color:var(--green)}.neg{color:var(--red)}.gld{color:var(--gold)}

.info-bar{
  background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:.6rem .9rem;margin-bottom:.6rem;display:flex;flex-wrap:wrap;gap:1.25rem
}
.ii .il{font-size:.58rem;text-transform:uppercase;letter-spacing:.7px;color:var(--dim)}
.ii .iv{font-size:.76rem;margin-top:.1rem}

.sym-row{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.6rem}
.sym{
  background:rgba(245,166,35,.08);border:1px solid rgba(245,166,35,.22);
  color:var(--gold);padding:.22rem .55rem;border-radius:5px;
  font-size:.7rem;font-weight:600
}

.card{background:var(--card);border:1px solid var(--border);border-radius:8px;
  margin-bottom:.6rem;overflow:hidden}
.ch{
  padding:.6rem .9rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between
}
.ch h2{font-size:.68rem;text-transform:uppercase;letter-spacing:.8px;color:var(--dim)}
.cnt{background:#1e1e1e;color:var(--text);border-radius:100px;padding:.1rem .45rem;font-size:.66rem}

.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:480px}
th{text-align:left;padding:.5rem .65rem;font-size:.6rem;text-transform:uppercase;
  letter-spacing:.7px;color:var(--dim);border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:.5rem .65rem;font-size:.76rem;border-bottom:1px solid #1b1b1b;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.016)}
.buy{color:var(--green);font-weight:600}.sell{color:var(--red);font-weight:600}

.empty{padding:1.75rem;text-align:center;color:var(--dim);font-size:.8rem}
footer{text-align:center;color:var(--dim);font-size:.66rem;padding:.5rem 1rem}
</style>
</head>
<body>
<div id="prog"></div>
<header>
  <h1>Trading Bot Dashboard</h1>
  <div id="badge" class="badge stop">
    <div id="dot" class="dot"></div>
    <span id="st">Loading</span>
  </div>
</header>

<main>
  <!-- Stat cards -->
  <div class="grid4">
    <div class="stat">
      <div class="lbl">Balance (est.)</div>
      <div class="val gld" id="balance">—</div>
      <div class="sub" id="bal-sub">&nbsp;</div>
    </div>
    <div class="stat">
      <div class="lbl">Win Rate</div>
      <div class="val" id="wr">—</div>
      <div class="sub" id="wr-sub">&nbsp;</div>
    </div>
    <div class="stat">
      <div class="lbl">Daily P&amp;L</div>
      <div class="val" id="dpnl">—</div>
      <div class="sub">Today UTC</div>
    </div>
    <div class="stat">
      <div class="lbl">Total Profit</div>
      <div class="val" id="tpnl">—</div>
      <div class="sub">All sessions</div>
    </div>
  </div>

  <!-- Info bar -->
  <div class="info-bar">
    <div class="ii"><div class="il">Session Start</div><div class="iv" id="ss">—</div></div>
    <div class="ii"><div class="il">Last Signal</div><div class="iv" id="ls">—</div></div>
    <div class="ii"><div class="il">Best Trade</div><div class="iv pos" id="bt">—</div></div>
    <div class="ii"><div class="il">Worst Trade</div><div class="iv neg" id="wt">—</div></div>
    <div class="ii"><div class="il">Updated</div><div class="iv" id="ra">—</div></div>
  </div>

  <!-- Active symbols -->
  <div class="sym-row" id="syms"></div>

  <!-- Open positions -->
  <div class="card">
    <div class="ch">
      <h2>Open Positions</h2>
      <span class="cnt" id="op-cnt">0</span>
    </div>
    <div id="op-body"><div class="empty">Loading…</div></div>
  </div>

  <!-- Recent closed trades -->
  <div class="card">
    <div class="ch">
      <h2>Recent Trades (last 20)</h2>
      <span class="cnt" id="rt-cnt">0</span>
    </div>
    <div id="rt-body"><div class="empty">Loading…</div></div>
  </div>
</main>

<footer id="foot">Auto-refreshes every 30 seconds &middot; Read-only</footer>

<script>
const $ = id => document.getElementById(id);
let tick = 30, timer;
const bar = $('prog');

function n(v, d=2) {
  if (v === null || v === undefined) return '—';
  return (+v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
}
function dt(s) {
  if (!s) return '—';
  return s.replace('T', ' ').slice(0, 16);
}
function pc(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : ''; }
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function sign(v) { return v > 0 ? '+' : ''; }

function render(d) {
  // Status badge
  const run = d.bot_running;
  $('badge').className = 'badge ' + (run ? 'run' : 'stop');
  $('dot').className   = 'dot' + (run ? ' pulse' : '');
  $('st').textContent  = run ? 'Running' : 'Stopped';

  // Balance
  $('balance').textContent = n(d.balance, 0);
  $('bal-sub').textContent = run
    ? 'Active session (excl. unrealized)'
    : 'Last session close';

  // Win rate
  const wr = $('wr');
  wr.textContent  = d.win_rate + '%';
  wr.className    = 'val ' + (d.win_rate >= 50 ? 'pos' : 'neg');
  $('wr-sub').textContent = d.winning_trades + ' wins / ' + d.total_trades + ' trades';

  // Daily P&L
  const dp = $('dpnl');
  dp.textContent = sign(d.daily_pnl) + n(d.daily_pnl);
  dp.className   = 'val ' + pc(d.daily_pnl);

  // Total profit
  const tp = $('tpnl');
  tp.textContent = sign(d.total_profit) + n(d.total_profit);
  tp.className   = 'val ' + pc(d.total_profit);

  // Info bar
  $('ss').textContent = dt(d.session_start);
  $('ls').textContent = dt(d.last_signal);
  $('bt').textContent = d.best_trade  > 0 ? '+' + n(d.best_trade)  : n(d.best_trade);
  $('wt').textContent = n(d.worst_trade);
  $('ra').textContent = d.refreshed_at;

  // Symbols
  $('syms').innerHTML = d.symbols.length
    ? d.symbols.map(s => `<span class="sym">${esc(s)}</span>`).join('')
    : '<span style="color:#444;font-size:.72rem">No trades recorded yet</span>';

  // Open positions
  $('op-cnt').textContent = d.open_positions.length;
  if (!d.open_positions.length) {
    $('op-body').innerHTML = '<div class="empty">No open positions</div>';
  } else {
    $('op-body').innerHTML =
      '<div class="tw"><table><thead><tr>'
      + '<th>Ticket</th><th>Symbol</th><th>Dir</th><th>Opened</th>'
      + '<th>Entry</th><th>Lot</th><th>SL</th><th>TP</th>'
      + '</tr></thead><tbody>'
      + d.open_positions.map(p =>
          `<tr>
            <td>${p.ticket}</td>
            <td>${esc(p.symbol)}</td>
            <td class="${p.direction === 'BUY' ? 'buy' : 'sell'}">${esc(p.direction)}</td>
            <td>${dt(p.open_time)}</td>
            <td>${n(p.entry_price, 2)}</td>
            <td>${n(p.volume, 2)}</td>
            <td>${n(p.stop_loss, 2)}</td>
            <td>${n(p.take_profit, 2)}</td>
          </tr>`
        ).join('')
      + '</tbody></table></div>';
  }

  // Recent trades
  $('rt-cnt').textContent = d.recent_trades.length;
  if (!d.recent_trades.length) {
    $('rt-body').innerHTML = '<div class="empty">No closed trades yet</div>';
  } else {
    $('rt-body').innerHTML =
      '<div class="tw"><table><thead><tr>'
      + '<th>Ticket</th><th>Symbol</th><th>Dir</th><th>Closed</th>'
      + '<th>Entry</th><th>Exit</th><th>P&amp;L</th><th>RR</th><th>Reason</th>'
      + '</tr></thead><tbody>'
      + d.recent_trades.map(t =>
          `<tr>
            <td>${t.ticket}</td>
            <td>${esc(t.symbol)}</td>
            <td class="${t.direction === 'BUY' ? 'buy' : 'sell'}">${esc(t.direction)}</td>
            <td>${dt(t.close_time)}</td>
            <td>${n(t.entry_price, 2)}</td>
            <td>${n(t.exit_price, 2)}</td>
            <td class="${pc(t.profit)}">${sign(t.profit)}${n(t.profit, 2)}</td>
            <td>${t.rr_ratio ? n(t.rr_ratio, 2) : '—'}</td>
            <td style="color:#4a4a4a;font-size:.7rem">${esc(t.exit_reason || '—')}</td>
          </tr>`
        ).join('')
      + '</tbody></table></div>';
  }
}

function startCountdown() {
  clearInterval(timer);
  tick = 30;
  bar.style.transition = 'none';
  bar.style.width = '100%';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    bar.style.transition = 'width 30s linear';
    bar.style.width = '0';
  }));
  timer = setInterval(() => {
    tick--;
    $('foot').textContent = `Refreshing in ${tick}s · Read-only`;
    if (tick <= 0) { clearInterval(timer); load(); }
  }, 1000);
}

function load() {
  fetch('/api/data')
    .then(r => r.json())
    .then(d => {
      if (!d.db_exists) {
        $('st').textContent = 'No DB';
        $('foot').textContent = 'Database not found — start the bot first.';
        return;
      }
      render(d);
      startCountdown();
    })
    .catch(() => {
      $('st').textContent = 'Error';
      $('foot').textContent = 'Failed to reach server — retrying in 30s';
      setTimeout(load, 30000);
    });
}

load();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print(f"Dashboard: http://localhost:5000")
    print(f"Database:  {DB_PATH}")
    print(f"On phone:  http://<your-PC-LAN-IP>:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
