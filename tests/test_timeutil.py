from datetime import date, datetime, timedelta, timezone

import pytest

from weekburn.timeutil import parse_range, parse_since, range_window

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value,delta",
    [("7d", timedelta(days=7)), ("48h", timedelta(hours=48)), ("2w", timedelta(weeks=2)), (" 1D ", timedelta(days=1))],
)
def test_parse_since_relative(value, delta):
    assert parse_since(value, NOW) == NOW - delta


def test_parse_since_date_is_start_of_day():
    assert parse_since("2026-10-20", NOW, tz=timezone.utc) == datetime(2026, 10, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["", "7", "seven days", "0d", "2026-13-01"])
def test_parse_since_rejects_bad_values(value):
    with pytest.raises(ValueError):
        parse_since(value, NOW)


def test_parse_range_and_window_include_last_day():
    days = parse_range("2026-10-10:2026-10-16")
    assert days == (date(2026, 10, 10), date(2026, 10, 16))
    start, end = range_window(days, tz=timezone.utc)
    assert start == datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["2026-10-10", "2026-10-16:2026-10-10", "a:b", "2026-10-10:2026-10-11:2026-10-12"])
def test_parse_range_rejects_bad_values(value):
    with pytest.raises(ValueError):
        parse_range(value)
