"""
trade_snapshot.py — saves a chart image every time the bot opens a trade.

Saves to: snapshots/SYMBOL_DIRECTION_YYYYMMDD_HHMMSS.png
Shows:
  - M5 candlesticks with Bollinger Bands + MA50
  - RSI panel with bull/bear zone shading
  - MACD panel
  - Entry marker, SL line, TP line
  - Signal reasons text box
"""
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = "snapshots"


def _ensure_dir():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def save_trade_snapshot(
    symbol:      str,
    direction:   str,           # "BUY" or "SELL"
    entry_price: float,
    sl:          float,
    tp:          float,
    signal_data: Dict[str, Any],
    entry_df,                   # pandas DataFrame — M5 OHLCV candles
    rsi_values:  List[float],
    macd_line:   List[float],
    macd_signal: List[float],
    macd_hist:   List[float],
    bb_upper:    List[float],
    bb_lower:    List[float],
    bb_mid:      List[float],
    ticket:      Optional[int] = None,
) -> Optional[str]:
    """
    Render and save a trade snapshot PNG.
    Returns the file path, or None if matplotlib is unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")           # headless — no GUI needed
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import matplotlib.gridspec as gridspec
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not installed — skipping trade snapshot. pip install matplotlib")
        return None

    _ensure_dir()

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{SNAPSHOT_DIR}/{symbol}_{direction}_{ts}.png"

    try:
        df = entry_df.copy().tail(80)   # last 80 M5 candles
        n  = len(df)
        x  = range(n)

        fig = plt.figure(figsize=(18, 12), facecolor="#0d1117")
        gs  = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.05)

        color_up   = "#26a69a"
        color_down = "#ef5350"
        color_bg   = "#0d1117"
        color_grid = "#21262d"
        color_text = "#e6edf3"

        # ── Panel 1: Price + BB + MA + Entry/SL/TP ────────────────────────────
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor(color_bg)
        ax1.tick_params(colors=color_text, labelsize=8)
        ax1.yaxis.label.set_color(color_text)
        for spine in ax1.spines.values():
            spine.set_edgecolor(color_grid)

        # Candlesticks
        for i, (_, row) in enumerate(df.iterrows()):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            col = color_up if c >= o else color_down
            ax1.plot([i, i], [l, h], color=col, linewidth=0.8)
            ax1.add_patch(mpatches.Rectangle(
                (i - 0.3, min(o, c)), 0.6, abs(c - o),
                facecolor=col, edgecolor=col, linewidth=0
            ))

        # Bollinger Bands
        bb_u = bb_upper[-n:] if len(bb_upper) >= n else bb_upper
        bb_l = bb_lower[-n:] if len(bb_lower) >= n else bb_lower
        bb_m = bb_mid[-n:]   if len(bb_mid)   >= n else bb_mid
        xi   = range(len(bb_u))
        ax1.plot(xi, bb_u, color="#7c8cf8", linewidth=0.8, alpha=0.7, label="BB Upper")
        ax1.plot(xi, bb_l, color="#7c8cf8", linewidth=0.8, alpha=0.7, label="BB Lower")
        ax1.plot(xi, bb_m, color="#7c8cf8", linewidth=0.5, alpha=0.4, linestyle="--")
        ax1.fill_between(xi, bb_u, bb_l, alpha=0.05, color="#7c8cf8")

        # Entry / SL / TP lines
        is_buy = direction == "BUY"
        ax1.axhline(entry_price, color="#f0c040", linewidth=1.2, linestyle="-",  label=f"Entry {entry_price:.2f}")
        ax1.axhline(sl,          color=color_down, linewidth=1.0, linestyle="--", label=f"SL {sl:.2f}")
        ax1.axhline(tp,          color=color_up,   linewidth=1.0, linestyle="--", label=f"TP {tp:.2f}")

        # Entry arrow on last candle
        last_i = n - 1
        arrow_y = df["low"].iloc[-1]  if is_buy else df["high"].iloc[-1]
        dy      = (entry_price - arrow_y) * 0.3
        ax1.annotate(
            f"{'▲ BUY' if is_buy else '▼ SELL'}",
            xy=(last_i, entry_price),
            xytext=(last_i, arrow_y - dy),
            color="#f0c040", fontsize=11, fontweight="bold",
            ha="center",
            arrowprops=dict(arrowstyle="->", color="#f0c040", lw=1.5),
        )

        ax1.set_xlim(-1, n + 1)
        ax1.grid(color=color_grid, linewidth=0.4)
        ax1.legend(loc="upper left", fontsize=7, facecolor=color_bg,
                   labelcolor=color_text, framealpha=0.7)

        # Title
        reasons_short = " | ".join(signal_data.get("reasons", [])[:4])
        score         = signal_data.get("score", 0)
        conf          = signal_data.get("confidence", "")
        ticket_str    = f"  Ticket #{ticket}" if ticket else ""
        ax1.set_title(
            f"{symbol}  {direction}  —  Score {score}  {conf}{ticket_str}\n"
            f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}  |  "
            f"Entry={entry_price:.2f}  SL={sl:.2f}  TP={tp:.2f}\n"
            f"{reasons_short}",
            color=color_text, fontsize=9, pad=6, loc="left"
        )

        # ── Panel 2: RSI ───────────────────────────────────────────────────────
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.set_facecolor(color_bg)
        ax2.tick_params(colors=color_text, labelsize=7)
        for spine in ax2.spines.values():
            spine.set_edgecolor(color_grid)

        rsi = rsi_values[-n:] if len(rsi_values) >= n else rsi_values
        rx  = range(len(rsi))
        ax2.plot(rx, rsi, color="#ab47bc", linewidth=1.0)
        ax2.axhline(70, color=color_down, linewidth=0.6, linestyle="--", alpha=0.6)
        ax2.axhline(30, color=color_up,   linewidth=0.6, linestyle="--", alpha=0.6)
        # Zone shading
        ax2.axhspan(35, 60, alpha=0.07, color=color_up,   label="Bull zone")
        ax2.axhspan(40, 65, alpha=0.07, color=color_down, label="Bear zone")
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("RSI", color=color_text, fontsize=8)
        ax2.grid(color=color_grid, linewidth=0.4)
        ax2.legend(loc="upper left", fontsize=6, facecolor=color_bg,
                   labelcolor=color_text, framealpha=0.5)

        # ── Panel 3: MACD ──────────────────────────────────────────────────────
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.set_facecolor(color_bg)
        ax3.tick_params(colors=color_text, labelsize=7)
        for spine in ax3.spines.values():
            spine.set_edgecolor(color_grid)

        ml  = macd_line[-n:]   if len(macd_line)   >= n else macd_line
        ms  = macd_signal[-n:] if len(macd_signal) >= n else macd_signal
        mh  = macd_hist[-n:]   if len(macd_hist)   >= n else macd_hist
        mx  = range(len(ml))
        ax3.plot(mx, ml, color="#26a69a", linewidth=0.9, label="MACD")
        ax3.plot(mx, ms, color="#ef5350", linewidth=0.9, label="Signal")
        bar_colors = [color_up if v >= 0 else color_down for v in mh]
        ax3.bar(range(len(mh)), mh, color=bar_colors, alpha=0.6, width=0.8)
        ax3.axhline(0, color=color_grid, linewidth=0.6)
        ax3.set_ylabel("MACD", color=color_text, fontsize=8)
        ax3.legend(loc="upper left", fontsize=6, facecolor=color_bg,
                   labelcolor=color_text, framealpha=0.5)
        ax3.grid(color=color_grid, linewidth=0.4)

        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)

        plt.savefig(filename, dpi=130, bbox_inches="tight", facecolor=color_bg)
        plt.close(fig)
        logger.info(f"Trade snapshot saved: {filename}")
        return filename

    except Exception as exc:
        logger.warning(f"Trade snapshot failed: {exc}")
        return None
