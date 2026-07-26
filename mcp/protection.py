"""Live anti-shock protection: weekend flatten window + (optional) news blackout.

Backtest attribution showed the weekend-gap flatten does ~all the drawdown
reduction; the news calendar is optional. These helpers answer, for a given
current UTC time, whether trading should be paused and open baskets flattened.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import calendar_filter as cal
from config import Config


def weekend_block(now: datetime, cfg: Config) -> bool:
    """True while inside the weekend flatten/pause window (times are UTC).

    Python weekday(): Mon=0 .. Fri=4, Sat=5, Sun=6.
    """
    if not cfg.weekend_flatten:
        return False
    dow = now.weekday()
    minutes = now.hour * 60 + now.minute
    close_min = cfg.weekend_fri_close_hour * 60 - cfg.weekend_pre_min
    if dow == 4:                       # Friday: after pre-close cutoff
        return minutes >= close_min
    if dow == 5:                       # Saturday
        return True
    if dow == 6:                       # Sunday: before reopen + a post-open settle buffer
        return minutes < cfg.weekend_sun_reopen_hour * 60 + cfg.weekend_reopen_buffer_min
    return False


def news_block(now: datetime, cfg: Config,
               events_csv: str = "data/news_events.csv") -> bool:
    """True while inside a high-impact news window (optional; off by default)."""
    if not cfg.news_filter:
        return False
    events = []
    if cfg.news_use_nfp:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = (month_start + timedelta(days=32)).replace(day=1)
        events += cal.nfp_events(month_start, nxt)
    events += cal.load_events_csv(events_csv)
    for e in events:
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        if e - timedelta(minutes=cfg.news_pre_min) <= now <= e + timedelta(minutes=cfg.news_post_min):
            return True
    return False


def protection_reason(now: datetime, cfg: Config) -> str | None:
    """Return a short reason if trading should be paused/flattened, else None."""
    if weekend_block(now, cfg):
        return "weekend flatten window"
    if news_block(now, cfg):
        return "news blackout window"
    return None
