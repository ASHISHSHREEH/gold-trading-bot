"""
ai_commentary.py — generates a brief narrative trade analysis using the Claude API.

Requires:
    pip install anthropic
    ANTHROPIC_API_KEY=sk-ant-... in .env

If the key is absent or the call fails the function returns None and the bot
continues normally — commentary is best-effort and never blocks a trade.
"""
import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def get_trade_commentary(
    symbol:    str,
    signal:    Dict[str, Any],
    entry:     Dict[str, Any],
    htf:       Dict[str, Any],
    trend:     Dict[str, Any],
    confirm:   Dict[str, Any],
    timing:    Dict[str, Any],
    execution: Dict[str, Any],
) -> Optional[str]:
    """
    Ask Claude for a 3–4 sentence trade narrative.
    Returns None if the API key is missing, the package is not installed, or the
    request fails for any reason.
    """
    if not _API_KEY:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("ai_commentary: 'anthropic' not installed — run: pip install anthropic")
        return None

    direction   = execution["direction"]
    entry_price = execution["entry_price"]
    sl          = execution["stop_loss"]
    tp          = execution["take_profit"]
    sl_dist     = abs(sl - entry_price)
    rr          = round(abs(tp - entry_price) / sl_dist, 2) if sl_dist > 0 else 0

    reasons_text = "\n".join(f"- {r}" for r in signal.get("reasons", []))
    bb_pos = (entry.get("bb") or {}).get("position", "N/A")
    rsi_str = f"{entry.get('rsi'):.1f}" if entry.get("rsi") is not None else "N/A"

    prompt = f"""You are a concise institutional trading analyst. A {direction} trade just opened on {symbol}.

Trade Setup:
- Direction: {direction}
- Entry: {entry_price:.2f}  SL: {sl:.2f}  TP: {tp:.2f}  R:R {rr}:1
- Lots: {execution.get('volume', 0)}

Multi-Timeframe Context:
- H4 (big-picture): {htf.get('trend', 'N/A')} | price {htf.get('price', 0):.2f} | MA50 {htf.get('ma_fast', 0):.2f} | MA200 {htf.get('ma_slow', 0):.2f}
- H1 (major trend): {trend.get('trend', 'N/A')} | price {trend.get('price', 0):.2f} | MA50 {trend.get('ma_fast', 0):.2f} | MA200 {trend.get('ma_slow', 0):.2f}
- M15 (confirmation): {confirm.get('ma_trend', 'N/A')} | MACD {confirm.get('macd', 'N/A')}
- M5 (entry): RSI {rsi_str} | BB {bb_pos} | ATR {entry.get('atr', 0):.2f}
- M1 (timing): {timing.get('direction', 'N/A')} | MACD {timing.get('macd', 'N/A')} | RSI {timing.get('rsi', 'N/A')}

Signal confluence ({signal.get('score', 0)}/5 points):
{reasons_text}

Write a 3–4 sentence trade narrative for a Telegram alert. Be specific about WHY this trade was taken, the key confluence factors, and the primary risk to watch. Use plain text only — no markdown, no bullet points, no headers. Keep it under 150 words."""

    try:
        client = anthropic.Anthropic(api_key=_API_KEY)
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "").strip()
        return text or None
    except Exception as exc:
        logger.warning("ai_commentary: API call failed — %s", exc)
        return None


def send_trade_commentary_async(
    symbol:    str,
    signal:    Dict[str, Any],
    entry:     Dict[str, Any],
    htf:       Dict[str, Any],
    trend:     Dict[str, Any],
    confirm:   Dict[str, Any],
    timing:    Dict[str, Any],
    execution: Dict[str, Any],
    callback:  Callable[[str, str], None],
) -> None:
    """
    Fire get_trade_commentary in a daemon thread and call callback(symbol, text).
    The main trading loop returns immediately; the Telegram message follows ~1-2 s later.
    """
    def _run():
        commentary = get_trade_commentary(
            symbol=symbol, signal=signal, entry=entry,
            htf=htf, trend=trend, confirm=confirm,
            timing=timing, execution=execution,
        )
        if commentary:
            callback(symbol, commentary)

    threading.Thread(target=_run, daemon=True).start()
