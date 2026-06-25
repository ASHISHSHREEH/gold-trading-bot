"""
Read-only monitoring dashboard for the gold trading bot.
Reads from data/trading_mt5.db — no MT5 connection required.

Usage:
    python dashboard.py
    Open http://localhost:5000 in a browser or phone (use LAN IP on phone)
"""
import calendar
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string

DB_PATH         = Path(__file__).parent / "data" / "trading_mt5.db"
LIVE_STATE_PATH = Path(__file__).parent / "data" / "live_state.json"

app = Flask(__name__)


# ── Live-state JSON reader ─────────────────────────────────────────────────────

def _read_live_state() -> dict:
    try:
        if LIVE_STATE_PATH.exists():
            with open(LIVE_STATE_PATH) as fh:
                return json.load(fh)
    except Exception:
        pass
    return {}


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

    # ── Live data from JSON (written by bot each scan) ─────────────────────────
    live           = _read_live_state()
    equity         = live.get("equity", 0)
    balance_val    = live.get("balance", 0)
    open_positions = live.get("open_positions", [])
    last_scan_time = live.get("last_scan_time")

    # ── Bot running detection from DB session ──────────────────────────────────
    session     = _q1("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
    bot_running = bool(session and session.get("end_time") is None)

    # ── Closed-trade stats from DB ─────────────────────────────────────────────
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

    # Today's P&L (from DB)
    today = date.today().isoformat()
    daily_pnl = _q1(
        "SELECT COALESCE(SUM(profit), 0) AS d FROM trades "
        "WHERE date(close_time) = ? AND profit IS NOT NULL",
        (today,),
    ).get("d") or 0

    # Monthly P&L calendar (current month, grouped by date)
    now = datetime.now(timezone.utc)
    month_start = date(now.year, now.month, 1)
    month_end   = date(now.year, now.month, calendar.monthrange(now.year, now.month)[1])
    monthly_rows = _q(
        "SELECT date(close_time) AS trade_date, COALESCE(SUM(profit),0) AS day_pnl "
        "FROM trades "
        "WHERE close_time IS NOT NULL AND profit IS NOT NULL "
        "AND date(close_time) >= ? AND date(close_time) <= ? "
        "GROUP BY date(close_time)",
        (month_start.isoformat(), month_end.isoformat()),
    )
    monthly_pnl = {r["trade_date"]: round(float(r["day_pnl"]), 2) for r in monthly_rows}

    # Symbols seen across all trades (from DB)
    symbols = [r["symbol"] for r in _q("SELECT DISTINCT symbol FROM trades ORDER BY symbol")]

    # Last 20 closed trades (from DB)
    recent_trades = _q("""
        SELECT ticket, symbol, direction, open_time, close_time,
               entry_price, exit_price, profit, exit_reason, rr_ratio
          FROM trades
         WHERE close_time IS NOT NULL
         ORDER BY close_time DESC
         LIMIT 20
    """)

    return jsonify(
        db_exists      = db_exists,
        bot_running    = bot_running,
        session_start  = session.get("start_time") if session else None,
        balance        = round(float(balance_val), 2),
        equity         = round(float(equity), 2),
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
        monthly_pnl    = monthly_pnl,
        last_scan_time = last_scan_time,
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
#charts{margin-bottom:.6rem}
.chart-wrap{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:.6rem}
.chart-sym{font-size:.75rem;font-weight:600;color:var(--text)}
.chart-tv{font-size:.62rem;color:var(--dim);margin-left:.5rem}
.chart-waiting{padding:2rem;text-align:center;color:var(--dim);font-size:.8rem}
</style>
<script src="https://s3.tradingview.com/tv.js"></script>
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
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem">
        <div>
          <div class="lbl">Balance</div>
          <div class="val gld" id="balance">—</div>
        </div>
        <div style="text-align:right">
          <div class="lbl">Equity</div>
          <div class="val pos" id="equity">—</div>
        </div>
      </div>
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
    <div class="ii"><div class="il">Last Scan</div><div class="iv" id="ls">—</div></div>
    <div class="ii"><div class="il">Best Trade</div><div class="iv pos" id="bt">—</div></div>
    <div class="ii"><div class="il">Worst Trade</div><div class="iv neg" id="wt">—</div></div>
    <div class="ii"><div class="il">Updated</div><div class="iv" id="ra">—</div></div>
  </div>

  <!-- Active symbols -->
  <div class="sym-row" id="syms"></div>

  <!-- Live TradingView charts (one per open symbol) -->
  <div id="charts"></div>

  <!-- Open positions -->
  <div class="card">
    <div class="ch">
      <h2>Open Positions</h2>
      <span class="cnt" id="op-cnt">0</span>
    </div>
    <div id="op-body"><div class="empty">Loading…</div></div>
  </div>

  <!-- Monthly P&L calendar -->
  <div class="card">
    <div class="ch">
      <h2>Monthly P&amp;L &mdash; <span id="cal-month"></span></h2>
    </div>
    <div id="cal-body" style="padding:.65rem"></div>
  </div>

  <!-- Recent closed trades -->
  <div class="card">
    <div class="ch">
      <h2>Recent Trades</h2>
      <span class="cnt" id="rt-cnt">0</span>
    </div>
    <div id="rt-body"><div class="empty">Loading…</div></div>
    <div id="rt-toggle" style="display:none;padding:.5rem;text-align:center">
      <button id="rt-btn" onclick="toggleTrades()"
        style="background:#1e1e1e;color:var(--gold);border:1px solid rgba(245,166,35,.3);
               border-radius:6px;padding:.35rem 1rem;font-size:.72rem;cursor:pointer">
        Show All Trades &#9660;
      </button>
    </div>
  </div>
</main>

<footer id="foot">Auto-refreshes every 30 seconds &middot; Read-only</footer>

<script>
const $ = id => document.getElementById(id);
let tick = 30, timer;
const bar = $('prog');
let _tradesExpanded = false;

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

  // Balance + Equity (from live JSON)
  $('balance').textContent = n(d.balance, 0);
  $('equity').textContent  = n(d.equity,  0);
  $('bal-sub').textContent = d.balance > 0 ? 'Live from MT5' : 'Bot not running';

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
  $('ls').textContent = dt(d.last_scan_time);
  $('bt').textContent = d.best_trade  > 0 ? '+' + n(d.best_trade)  : n(d.best_trade);
  $('wt').textContent = n(d.worst_trade);
  $('ra').textContent = d.refreshed_at;

  // Symbols
  $('syms').innerHTML = d.symbols.length
    ? d.symbols.map(s => `<span class="sym">${esc(s)}</span>`).join('')
    : '<span style="color:#444;font-size:.72rem">No trades recorded yet</span>';

  // Charts
  renderCharts(d.open_positions);

  // Open positions
  $('op-cnt').textContent = d.open_positions.length;
  if (!d.open_positions.length) {
    $('op-body').innerHTML = '<div class="empty">No open positions</div>';
  } else {
    $('op-body').innerHTML =
      '<div class="tw"><table><thead><tr>'
      + '<th>Ticket</th><th>Symbol</th><th>Dir</th><th>Entry</th>'
      + '<th>Current</th><th>Lot</th><th>P&amp;L</th><th>SL</th><th>TP</th>'
      + '</tr></thead><tbody>'
      + d.open_positions.map(p =>
          `<tr>
            <td>${p.ticket}</td>
            <td>${esc(p.symbol)}</td>
            <td class="${p.direction === 'BUY' ? 'buy' : 'sell'}">${esc(p.direction)}</td>
            <td>${n(p.entry_price, 2)}</td>
            <td>${n(p.current_price, 2)}</td>
            <td>${n(p.volume, 2)}</td>
            <td class="${pc(p.profit)}">${sign(p.profit)}${n(p.profit, 2)}</td>
            <td>${n(p.sl, 2)}</td>
            <td>${n(p.tp, 2)}</td>
          </tr>`
        ).join('')
      + '</tbody></table></div>';
  }

  // Monthly P&L calendar
  renderCalendar(d.monthly_pnl || {});

  // Recent trades
  $('rt-cnt').textContent = d.recent_trades.length;
  if (!d.recent_trades.length) {
    $('rt-body').innerHTML = '<div class="empty">No closed trades yet</div>';
    $('rt-toggle').style.display = 'none';
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
    if (d.recent_trades.length > 5) {
      $('rt-toggle').style.display = '';
      applyTradeCollapse();
    } else {
      $('rt-toggle').style.display = 'none';
    }
  }
}

function applyTradeCollapse() {
  const rows = document.querySelectorAll('#rt-body tbody tr');
  rows.forEach((r, i) => { r.style.display = (i >= 5 && !_tradesExpanded) ? 'none' : ''; });
  $('rt-btn').innerHTML = _tradesExpanded ? 'Show Less &#9650;' : 'Show All Trades &#9660;';
}

function toggleTrades() {
  _tradesExpanded = !_tradesExpanded;
  applyTradeCollapse();
}

function renderCalendar(data) {
  const now   = new Date();
  const year  = now.getFullYear();
  const month = now.getMonth();
  $('cal-month').textContent = now.toLocaleString('default', {month:'long', year:'numeric'});

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDay    = new Date(year, month, 1).getDay();

  let html = '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px;font-size:.6rem">';
  ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].forEach(d => {
    html += `<div style="text-align:center;color:var(--dim);padding:.2rem 0;font-weight:600">${d}</div>`;
  });
  for (let i = 0; i < firstDay; i++) html += '<div></div>';

  for (let day = 1; day <= daysInMonth; day++) {
    const mo      = String(month + 1).padStart(2, '0');
    const dy      = String(day).padStart(2, '0');
    const key     = `${year}-${mo}-${dy}`;
    const pnl     = data[key];
    const isToday = day === now.getDate();

    let bg = '#1a1a1a', clr = '#444', amt = '';
    if (pnl !== undefined) {
      if (pnl > 0) {
        bg  = 'rgba(34,197,94,.15)'; clr = '#22c55e';
        amt = '+¥' + Math.round(pnl).toLocaleString();
      } else if (pnl < 0) {
        bg  = 'rgba(239,68,68,.15)'; clr = '#ef4444';
        amt = '-¥' + Math.abs(Math.round(pnl)).toLocaleString();
      } else {
        clr = '#666'; amt = '¥0';
      }
    }
    const border = isToday ? 'border:1px solid var(--gold)' : 'border:1px solid transparent';
    html += `<div style="background:${bg};border-radius:4px;padding:.25rem .15rem;text-align:center;min-height:40px;${border}">
      <div style="color:var(--dim);font-size:.55rem">${day}</div>
      <div style="color:${clr};font-size:.58rem;margin-top:.1rem;line-height:1.2;word-break:break-all">${amt}</div>
    </div>`;
  }
  html += '</div>';
  $('cal-body').innerHTML = html;
}

// ── TradingView charts ─────────────────────────────────────────────────────────
const TV_SYMBOLS = {
  'GOLD':       'OANDA:XAUUSD',
  '#USSPX500':  'SP:SPX',
  '#US100_M26': 'NASDAQ:NDX',
  '#Japan225':  'TVC:NI225',
};
let _chartSymKey = null;

function renderCharts(positions) {
  const syms   = [...new Set(positions.map(p => p.symbol))];
  const symKey = syms.slice().sort().join(',');
  if (symKey === _chartSymKey) return;   // symbols unchanged — no flicker
  _chartSymKey = symKey;

  const el = $('charts');

  if (!syms.length) {
    el.innerHTML = '<div class="chart-wrap"><div class="chart-waiting">Waiting for signal...</div></div>';
    return;
  }

  el.innerHTML = syms.map(sym => {
    const id   = 'tv_' + sym.replace(/[^a-zA-Z0-9]/g, '_');
    const tvSym = TV_SYMBOLS[sym] || sym;
    return `<div class="chart-wrap">
      <div class="ch">
        <h2 class="chart-sym">${esc(sym)}</h2>
        <span class="chart-tv">${esc(tvSym)}&nbsp;&bull;&nbsp;M15</span>
      </div>
      <div id="${id}"></div>
    </div>`;
  }).join('');

  if (!window.TradingView) return;
  syms.forEach(sym => {
    const id    = 'tv_' + sym.replace(/[^a-zA-Z0-9]/g, '_');
    const tvSym = TV_SYMBOLS[sym] || sym;
    new TradingView.widget({
      container_id:        id,
      symbol:              tvSym,
      interval:            '15',
      theme:               'dark',
      style:               '1',
      locale:              'en',
      width:               '100%',
      height:              400,
      timezone:            'Etc/UTC',
      hide_top_toolbar:    false,
      hide_side_toolbar:   false,
      enable_publishing:   false,
      allow_symbol_change: false,
    });
  });
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
