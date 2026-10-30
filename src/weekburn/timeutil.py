"""Turn --since and --before/--after values into time windows."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, tzinfo

_SINCE = re.compile(r"^\s*(\d+)\s*([hdw])\s*$", re.IGNORECASE)
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


def local_midnight(day: date, tz: tzinfo | None = None) -> datetime:
    """Start of ``day`` in ``tz`` (the machine's local time zone when tz is None)."""
    naive = datetime.combine(day, time.min)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def parse_since(value: str, now: datetime, tz: tzinfo | None = None) -> datetime:
    """'7d', '48h', '2w', or a date like '2026-10-20' (start of that day)."""
    m = _SINCE.match(value)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        if amount <= 0:
            raise ValueError("--since must be more than zero")
        return now - timedelta(**{_UNITS[unit]: amount})
    try:
        day = date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"cannot read --since {value!r}; use 7d, 48h, 2w or a date like 2026-10-20") from None
    return local_midnight(day, tz)


def parse_range(value: str) -> tuple[date, date]:
    """'2026-10-10:2026-10-16' -> (first day, last day), both included."""
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"cannot read {value!r}; use FIRST:LAST, for example 2026-10-10:2026-10-16")
    try:
        first, last = date.fromisoformat(parts[0].strip()), date.fromisoformat(parts[1].strip())
    except ValueError:
        raise ValueError(f"cannot read {value!r}; dates must look like 2026-10-10") from None
    if last < first:
        raise ValueError(f"{value!r} ends before it starts")
    return first, last


def range_window(days: tuple[date, date], tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """Whole local days: from the start of the first day to the start of the day after the last."""
    return local_midnight(days[0], tz), local_midnight(days[1] + timedelta(days=1), tz)
