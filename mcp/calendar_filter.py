"""Time-based anti-shock filter: news blackout windows + weekend-gap flatten.

Shocks in gold are mostly *scheduled*. Instead of a loss-based stop (which
mis-fires on normal drawdown), we flatten and pause around known event times.

Deterministic sources built in:
  * NFP  — first Friday of each month, 13:30 UTC
  * weekend gap — the last bar before a long market-closed gap

Extra events (CPI/FOMC/etc.) can be supplied via a CSV of UTC datetimes
(one ISO timestamp per line, e.g. 2025-03-12T12:30), path in cfg or
`data/news_events.csv`.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone


def _utc(ts) -> datetime:
    return datetime.fromtimestamp(int(ts), timezone.utc)


def weekend_flatten_mask(times, gap_hours: int = 8):
    """True on the last bar before a market-closed gap (flatten before it)."""
    n = len(times)
    mask = [False] * n
    if n == 0:
        return mask
    thr = gap_hours * 3600
    for i in range(n - 1):
        if int(times[i + 1]) - int(times[i]) > thr:
            mask[i] = True
    mask[n - 1] = True
    return mask


def nfp_events(start: datetime, end: datetime):
    """First Friday of each month at 13:30 UTC within [start, end]."""
    out = []
    y, m = start.year, start.month
    while datetime(y, m, 1, tzinfo=timezone.utc) <= end:
        d = datetime(y, m, 1, 13, 30, tzinfo=timezone.utc)
        while d.weekday() != 4:      # 4 = Friday
            d += timedelta(days=1)
        if start <= d <= end:
            out.append(d)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def load_events_csv(path: str):
    events = []
    if not path or not os.path.exists(path):
        return events
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            s = row[0].strip()
            if not s or s.lower().startswith("date"):
                continue
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                events.append(dt.astimezone(timezone.utc))
            except ValueError:
                continue
    return events


def news_blackout_mask(times, pre_min: int, post_min: int,
                       use_nfp: bool = True, events_csv: str = "data/news_events.csv"):
    """True on bars within [event-pre, event+post] of any high-impact event."""
    n = len(times)
    mask = [False] * n
    if n == 0:
        return mask
    start, end = _utc(times[0]), _utc(times[-1])
    events = []
    if use_nfp:
        events += nfp_events(start, end)
    events += [e for e in load_events_csv(events_csv) if start <= e <= end]
    if not events:
        return mask
    windows = [(e - timedelta(minutes=pre_min), e + timedelta(minutes=post_min)) for e in events]
    for i, ts in enumerate(times):
        dt = _utc(ts)
        for a, b in windows:
            if a <= dt <= b:
                mask[i] = True
                break
    return mask
