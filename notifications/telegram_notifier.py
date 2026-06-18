"""
telegram_notifier.py — sends alerts to Telegram when important events happen.

Setup:
  1. Create a bot via @BotFather → get TELEGRAM_BOT_TOKEN
  2. Get your chat ID via @userinfobot → set TELEGRAM_CHAT_ID
  3. Add both to your .env file

Alerts sent:
  - Bot started / stopped
  - Trade opened (symbol, direction, entry, SL, TP)
  - Trade closed (profit/loss, R:R)
  - Daily drawdown circuit breaker triggered
  - MT5 connection lost / reconnected
  - News blackout active
"""
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional
from urllib import request, parse, error

logger = logging.getLogger(__name__)

_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",   "")
_ENABLED    = bool(_BOT_TOKEN and _CHAT_ID)
_API_URL    = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"


def _send(text: str) -> None:
    """Send a message in a background thread so it never blocks the main loop."""
    if not _ENABLED:
        return

    def _post():
        try:
            payload = parse.urlencode({
                "chat_id":    _CHAT_ID,
                "text":       text,
                "parse_mode": "HTML",
            }).encode()
            req = request.Request(_API_URL, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning("Telegram: HTTP %d", resp.status)
        except error.URLError as exc:
            logger.warning("Telegram send failed: %s", exc)
        except Exception as exc:
            logger.debug("Telegram error: %s", exc)

    threading.Thread(target=_post, daemon=True).start()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Public alert functions ─────────────────────────────────────────────────────

def alert_bot_started(symbols: list, balance: float, currency: str, phase: int) -> None:
    _send(
        f"🤖 <b>Gold Bot STARTED</b>\n"
        f"⏰ {_ts()}\n"
        f"💰 Balance: {balance:,.2f} {currency}\n"
        f"📊 Symbols: {', '.join(symbols)}\n"
        f"🔒 Phase {phase} — Strict Mode"
    )


def alert_bot_stopped(reason: str = "Manual stop") -> None:
    _send(
        f"🛑 <b>Gold Bot STOPPED</b>\n"
        f"⏰ {_ts()}\n"
        f"📝 Reason: {reason}"
    )


def alert_trade_opened(
    symbol: str, direction: str, entry: float,
    sl: float, tp: float, lots: float, currency: str,
    score: int, reasons: list,
) -> None:
    icon = "🟢" if direction == "BUY" else "🔴"
    rr   = round(abs(tp - entry) / abs(sl - entry), 2) if abs(sl - entry) > 0 else 0
    _send(
        f"{icon} <b>TRADE OPENED — {symbol}</b>\n"
        f"⏰ {_ts()}\n"
        f"Direction : {direction}\n"
        f"Entry     : {entry:.2f}\n"
        f"SL        : {sl:.2f}    TP: {tp:.2f}    R:R {rr}\n"
        f"Lots      : {lots}\n"
        f"Score     : {score}/5\n"
        f"Reasons   : {' | '.join(reasons[:3])}"
    )


def alert_trade_closed(
    symbol: str, direction: str, profit: float,
    currency: str, ticket: int,
) -> None:
    icon   = "✅" if profit >= 0 else "❌"
    result = "WIN" if profit >= 0 else "LOSS"
    _send(
        f"{icon} <b>TRADE CLOSED — {symbol} {result}</b>\n"
        f"⏰ {_ts()}\n"
        f"Direction : {direction}\n"
        f"P&L       : {profit:+.2f} {currency}\n"
        f"Ticket    : {ticket}"
    )


def alert_drawdown(drawdown_pct: float, equity: float, currency: str) -> None:
    _send(
        f"⚠️ <b>DRAWDOWN CIRCUIT BREAKER</b>\n"
        f"⏰ {_ts()}\n"
        f"Drawdown  : {drawdown_pct:.1%}\n"
        f"Equity    : {equity:,.2f} {currency}\n"
        f"🚫 New entries blocked for rest of session."
    )


def alert_connection_lost() -> None:
    _send(
        f"📡 <b>MT5 CONNECTION LOST</b>\n"
        f"⏰ {_ts()}\n"
        f"Bot is attempting to reconnect..."
    )


def alert_connection_restored(balance: float, currency: str) -> None:
    _send(
        f"✅ <b>MT5 RECONNECTED</b>\n"
        f"⏰ {_ts()}\n"
        f"Balance: {balance:,.2f} {currency}"
    )


def alert_news_block(symbol: str, reason: str) -> None:
    _send(
        f"📰 <b>NEWS BLACKOUT — {symbol}</b>\n"
        f"⏰ {_ts()}\n"
        f"{reason}"
    )


def alert_ai_commentary(symbol: str, commentary: str) -> None:
    _send(f"🧠 <b>AI Analysis — {symbol}</b>\n{commentary}")


def alert_daily_summary(
    balance: float, equity: float, currency: str,
    trades_opened: int, trades_closed: int, net_pnl: float,
) -> None:
    pnl_icon = "📈" if net_pnl >= 0 else "📉"
    _send(
        f"{pnl_icon} <b>DAILY SUMMARY</b>\n"
        f"⏰ {_ts()}\n"
        f"Balance   : {balance:,.2f} {currency}\n"
        f"Equity    : {equity:,.2f} {currency}\n"
        f"Net P&L   : {net_pnl:+.2f} {currency}\n"
        f"Trades    : {trades_opened} opened  |  {trades_closed} closed"
    )
