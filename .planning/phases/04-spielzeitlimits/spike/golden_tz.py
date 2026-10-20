"""Golden Vectors: lokale Wochenplan-Zeiten (Europe/Berlin) als Epoch-Grenzen, inklusive Zeitumstellung.

Läuft mit jeder Python-Installation mit Zeitzonendaten (System-tzdata oder PyPI tzdata), z. B.:
docker run --rm -v "$PWD/.planning/phases/04-spielzeitlimits/spike:/s:ro" python:3.13-slim-trixie python -I /s/golden_tz.py
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


def epoch(day: date, at: time) -> int:
    return int(datetime.combine(day, at, tzinfo=TZ).timestamp())


def day_bounds(day: date) -> tuple[int, int]:
    start = epoch(day, time(0, 0))
    end = epoch(day + timedelta(days=1), time(0, 0))
    return start, end


for label, day in (
    ("Sa vor Umstellung", date(2026, 10, 24)),
    ("So Umstellung (25 h)", date(2026, 10, 25)),
    ("Mo nach Umstellung", date(2026, 10, 26)),
    ("So Sommerzeit-Beginn (23 h)", date(2026, 3, 29)),
):
    start, end = day_bounds(day)
    close = epoch(day, time(19, 0))
    print(f"{label}: {day.isoformat()} weekday={day.isoweekday()} Tag [{start}, {end}) = {(end - start) / 3600} h; "
          f"19:00 lokal = {close} = {datetime.fromtimestamp(close, ZoneInfo('UTC')).strftime('%H:%MZ')}")

# Nicht existierende lokale Zeit (Lücke 02:00 bis 03:00 am 29.03.2026) und doppelte (02:30 am 25.10.2026)
for label, day, at in (("Lücke 02:30", date(2026, 3, 29), time(2, 30)), ("doppelt 02:30", date(2026, 10, 25), time(2, 30))):
    stamp = epoch(day, at)
    print(f"{label}: {stamp} = {datetime.fromtimestamp(stamp, ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%MZ')}")
