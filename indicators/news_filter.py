"""
news_filter.py — two-layer news protection for live trading.

Layer 1: Economic calendar blackout
  - Hardcoded recurring high-impact events (NFP, CPI, FOMC, etc.)
  - Configurable buffer before/after each event
  - User can add extra blackout windows via NEWS_BLACKOUT env var

Layer 2: ATR volatility spike guard
  - Compares current ATR to its rolling average
  - If ATR > NEWS_ATR_SPIKE_MULT × average → market is in a fundamental move → block entry
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# ── Recurring high-impact event schedule ──────────────────────────────────────
# Format: (name, weekday, hour_utc, minute_utc, freq)
#   weekday : 0=Mon … 6=Sun, or None = use day_of_month logic
#   freq    : 'first_friday' | 'second_tuesday' | 'monthly_X' | 'weekly' | 'custom'
#
# All times in UTC.  Blackout = [event_time - BUFFER_BEFORE, event_time + BUFFER_AFTER]

_RECURRING_EVENTS = [
    # ── United States ──────────────────────────────────────────────────────────
    # NFP — first Friday of every month, 13:30 UTC (8:30 AM ET)
    {"name": "NFP",        "freq": "first_friday",    "hour": 13, "minute": 30},
    # CPI — ~2nd Tuesday/Wednesday, 13:30 UTC  (approx — varies by month)
    {"name": "US CPI",     "freq": "second_wednesday", "hour": 13, "minute": 30},
    # FOMC — 8 times per year, Wednesday 19:00 UTC (2:00 PM ET)
    # Can't predict exact dates without a live API — use manual override for FOMC
    # PPI — ~2nd Thursday, 13:30 UTC
    {"name": "US PPI",     "freq": "second_thursday",  "hour": 13, "minute": 30},
    # Retail Sales — ~2nd Wednesday, 13:30 UTC
    {"name": "Retail Sales", "freq": "second_wednesday", "hour": 13, "minute": 30},
    # GDP — last Wednesday of Jan, Apr, Jul, Oct  (advance estimate)
    # ISM Manufacturing — first business day of month, 15:00 UTC
    {"name": "ISM Mfg",   "freq": "first_monday",     "hour": 15, "minute": 0},
    # JOLTS — first Wednesday of month
    {"name": "JOLTS",     "freq": "first_wednesday",  "hour": 15, "minute": 0},

    # ── Gold-specific ──────────────────────────────────────────────────────────
    # US Dollar Index (DXY) rebalance Fridays ~21:00 UTC — mild but worth noting
    # Weekly Jobless Claims — every Thursday 13:30 UTC
    {"name": "Jobless Claims", "freq": "weekly_thursday", "hour": 13, "minute": 30},
]


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[datetime]:
    """Return the nth occurrence of weekday (0=Mon) in the given month."""
    count = 0
    for day in range(1, 32):
        try:
            dt = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            break
        if dt.weekday() == weekday:
            count += 1
            if count == n:
                return dt
    return None


def _event_times_this_month(now: datetime) -> List[Tuple[str, datetime]]:
    """Return all scheduled event datetimes for the current calendar month."""
    year, month = now.year, now.month
    results = []

    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    }

    for ev in _RECURRING_EVENTS:
        freq = ev["freq"]
        h, m = ev["hour"], ev["minute"]
        name = ev["name"]

        dt = None
        if freq == "first_friday":
            dt = _nth_weekday_of_month(year, month, 4, 1)
        elif freq.startswith("first_"):
            wd = weekday_map.get(freq[6:])
            if wd is not None:
                dt = _nth_weekday_of_month(year, month, wd, 1)
        elif freq.startswith("second_"):
            wd = weekday_map.get(freq[7:])
            if wd is not None:
                dt = _nth_weekday_of_month(year, month, wd, 2)
        elif freq.startswith("weekly_"):
            wd = weekday_map.get(freq[7:])
            if wd is not None:
                # find all occurrences this month
                for n in range(1, 6):
                    d = _nth_weekday_of_month(year, month, wd, n)
                    if d:
                        results.append((name, d.replace(hour=h, minute=m, second=0, microsecond=0)))
                continue

        if dt:
            results.append((name, dt.replace(hour=h, minute=m, second=0, microsecond=0)))

    return results


def _parse_custom_blackouts(env_val: str) -> List[Tuple[str, datetime]]:
    """
    Parse NEWS_BLACKOUT env var.
    Format: "FOMC 2026-06-11 19:00, PCE 2026-06-28 13:30"
    """
    results = []
    if not env_val:
        return results
    for entry in env_val.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split()
        if len(parts) < 3:
            continue
        try:
            name = parts[0]
            dt   = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M")
            dt   = dt.replace(tzinfo=timezone.utc)
            results.append((name, dt))
        except ValueError:
            logger.warning("news_filter: could not parse blackout entry '%s'", entry)
    return results


# ── ForexFactory live calendar ─────────────────────────────────────────────────

_ff_cache: list = []
_ff_fetched_at: float = 0.0
_FF_CACHE_TTL = 3600   # refresh once per hour


def _fetch_forexfactory_events() -> list:
    """
    Fetch this week's high-impact USD events from ForexFactory's public JSON feed.
    Returns list of (name, datetime_utc) tuples.
    Silently returns [] on any network/parse error.
    """
    global _ff_cache, _ff_fetched_at
    import time as _time

    if _time.time() - _ff_fetched_at < _FF_CACHE_TTL and _ff_cache:
        return _ff_cache

    try:
        from urllib import request as _req
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        req = _req.Request(url, headers={"User-Agent": "GoldBot/2.0"})
        with _req.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read().decode())

        results = []
        for ev in data:
            if ev.get("impact") != "High":
                continue
            if ev.get("currency") not in ("USD", "JPY"):
                continue
            try:
                dt_str = ev.get("date", "")
                if not dt_str:
                    continue
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                results.append((ev.get("title", "High-Impact Event"), dt))
            except Exception:
                continue

        _ff_cache      = results
        _ff_fetched_at = _time.time()
        logger.info("ForexFactory: loaded %d high-impact events this week", len(results))
        return results

    except Exception as exc:
        logger.debug("ForexFactory fetch failed (using hardcoded schedule): %s", exc)
        return _ff_cache   # return stale cache or []


# ── Public API ─────────────────────────────────────────────────────────────────

def is_news_blackout(
    buffer_before_min: int = 30,
    buffer_after_min:  int = 30,
    now:               Optional[datetime] = None,
) -> Tuple[bool, str]:
    """
    Check if current time falls within any news blackout window.

    Returns:
        (True, reason_string) if blocked
        (False, "")           if clear
    """
    if now is None:
        now = datetime.now(timezone.utc)

    before = timedelta(minutes=buffer_before_min)
    after  = timedelta(minutes=buffer_after_min)

    # Scheduled recurring events (this month + next month boundary)
    all_events = _event_times_this_month(now)
    # Also check next month for events near month boundaries
    if now.month == 12:
        all_events += _event_times_this_month(now.replace(year=now.year + 1, month=1))
    else:
        all_events += _event_times_this_month(now.replace(month=now.month + 1))

    # Live ForexFactory feed (overrides / supplements hardcoded schedule)
    all_events += _fetch_forexfactory_events()

    # Custom blackouts from env
    custom = _parse_custom_blackouts(os.getenv("NEWS_BLACKOUT", ""))
    all_events += custom

    for name, event_dt in all_events:
        window_start = event_dt - before
        window_end   = event_dt + after
        if window_start <= now <= window_end:
            mins_to = int((event_dt - now).total_seconds() / 60)
            if mins_to >= 0:
                reason = f"NEWS BLACKOUT: {name} in {mins_to} min ({event_dt.strftime('%H:%M')} UTC)"
            else:
                reason = f"NEWS BLACKOUT: post-{name} cooldown ({-mins_to} min ago)"
            return True, reason

    return False, ""


def check_atr_spike(
    current_atr:  float,
    atr_series,             # pandas Series or list of recent ATR values
    spike_mult:   float = 2.0,
    lookback:     int   = 20,
) -> Tuple[bool, str]:
    """
    Returns (True, reason) if the current ATR is spike_mult times the rolling average.
    This catches news volatility even without a calendar.

    Args:
        current_atr  : latest ATR value
        atr_series   : recent ATR values (list or Series)
        spike_mult   : threshold multiplier (default 2.0 = 2× normal)
        lookback     : how many bars to average
    """
    if current_atr is None or current_atr <= 0:
        return False, ""

    try:
        import numpy as np
        vals = list(atr_series)[-lookback - 1 : -1]   # exclude current bar
        if len(vals) < 5:
            return False, ""
        avg_atr = float(np.mean(vals))
        if avg_atr <= 0:
            return False, ""
        ratio = current_atr / avg_atr
        if ratio >= spike_mult:
            return True, (
                f"ATR SPIKE: current ATR {current_atr:.2f} is {ratio:.1f}× "
                f"the {lookback}-bar average ({avg_atr:.2f}) — likely news event"
            )
    except Exception as exc:
        logger.debug("check_atr_spike error: %s", exc)

    return False, ""
