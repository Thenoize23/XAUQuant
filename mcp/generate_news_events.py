"""Generate data/news_events.csv with real high-impact USD events (CPI + FOMC).

CPI released 8:30 AM ET, FOMC decision 2:00 PM ET. Converted to UTC with the US
Eastern DST rule (2nd Sun Mar .. 1st Sun Nov). NFP is added automatically by the
filter (first Friday 13:30 UTC), so it's not repeated here.

CPI 2025-2026 verified via BLS/usinflationcalculator/cpiinflationcalculator.
FOMC 2022-2026 are the Fed's scheduled decision dates. Some late-2025 CPI dates
were shifted by the government shutdown; windows are wide enough to tolerate it.
"""
from datetime import date, datetime, timedelta, timezone
import csv, os

# (year, month, day) decision/release day
FOMC = [
    (2022,1,26),(2022,3,16),(2022,5,4),(2022,6,15),(2022,7,27),(2022,9,21),(2022,11,2),(2022,12,14),
    (2023,2,1),(2023,3,22),(2023,5,3),(2023,6,14),(2023,7,26),(2023,9,20),(2023,11,1),(2023,12,13),
    (2024,1,31),(2024,3,20),(2024,5,1),(2024,6,12),(2024,7,31),(2024,9,18),(2024,11,7),(2024,12,18),
    (2025,1,29),(2025,3,19),(2025,5,7),(2025,6,18),(2025,7,30),(2025,9,17),(2025,10,29),(2025,12,10),
    (2026,1,28),(2026,3,18),(2026,4,29),(2026,6,17),(2026,7,29),(2026,9,16),(2026,10,28),(2026,12,9),
]
CPI = [
    # 2024 (best-effort)
    (2024,1,11),(2024,2,13),(2024,3,12),(2024,4,10),(2024,5,15),(2024,6,12),
    (2024,7,11),(2024,8,14),(2024,9,11),(2024,10,10),(2024,11,13),(2024,12,11),
    # 2025 (verified)
    (2025,1,15),(2025,2,12),(2025,3,12),(2025,4,10),(2025,5,13),(2025,6,11),
    (2025,7,15),(2025,8,12),(2025,9,11),(2025,10,24),(2025,11,13),(2025,12,10),
    # 2026 (verified)
    (2026,1,13),(2026,2,13),(2026,3,11),(2026,4,10),(2026,5,12),(2026,6,10),(2026,7,14),
]

def is_us_dst(d: date) -> bool:
    march = date(d.year, 3, 1)
    second_sun_mar = march + timedelta(days=(6 - march.weekday()) % 7 + 7)
    nov = date(d.year, 11, 1)
    first_sun_nov = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return second_sun_mar <= d < first_sun_nov

def et_to_utc(y, m, d, hh, mm):
    offset = 4 if is_us_dst(date(y, m, d)) else 5     # EDT=UTC-4, EST=UTC-5
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc) + timedelta(hours=offset)

rows = []
for (y, m, d) in CPI:
    rows.append((et_to_utc(y, m, d, 8, 30), "CPI"))
for (y, m, d) in FOMC:
    rows.append((et_to_utc(y, m, d, 14, 0), "FOMC"))
rows.sort()

os.makedirs("data", exist_ok=True)
out = "data/news_events.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["datetime_utc", "event"])
    for dt, kind in rows:
        w.writerow([dt.strftime("%Y-%m-%dT%H:%M"), kind])
print(f"wrote {len(rows)} events to {out} ({rows[0][0].date()} -> {rows[-1][0].date()})")
