import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
from conftest import Session

from weekburn.analyze import build_comparison
from weekburn.parse import load
from weekburn.render import verdict_lines
from weekburn.timeutil import range_window

UTC = timezone.utc
BEFORE = (date(2026, 10, 10), date(2026, 10, 16))
AFTER = (date(2026, 10, 24), date(2026, 10, 30))


def _period_sessions(projects, first_day: date, n: int, tokens_per_msg: float, rng, msgs=(3, 12), noise=0.3):
    for i in range(n):
        at = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=10 + 3 * i)
        k = int(rng.integers(*msgs))
        s = Session(projects)
        per_msg = tokens_per_msg * float(rng.lognormal(0, noise))
        for j in range(k):
            t = at + timedelta(minutes=2 * j)
            s.user(t).request(t, input=5, output=500, cache_write=1_000, cache_read=int(per_msg) - 1_505)
        s.write()


def _compare(projects, **kw):
    return build_comparison(
        load([projects]), BEFORE, AFTER, range_window(BEFORE, UTC), range_window(AFTER, UTC), **kw
    )


def test_clear_increase_is_detected(projects):
    rng = np.random.default_rng(1)
    _period_sessions(projects, BEFORE[0], 25, 100_000, rng)
    _period_sessions(projects, AFTER[0], 25, 200_000, rng)
    c = _compare(projects)
    tpm = c.metrics[0]
    assert c.changed and c.trimmed_changed
    assert 70 < tpm.change < 130
    assert tpm.change_ci[0] > 0
    assert tpm.before_ci[0] < tpm.before < tpm.before_ci[1]
    assert "Your usage per message changed" in verdict_lines(c)[0]
    assert "up" in verdict_lines(c)[0]


def test_same_distribution_gives_no_clear_change(projects):
    rng = np.random.default_rng(2)
    _period_sessions(projects, BEFORE[0], 25, 100_000, rng)
    _period_sessions(projects, AFTER[0], 25, 100_000, rng)
    c = _compare(projects)
    lo, hi = c.metrics[0].change_ci
    assert lo < 0 < hi
    assert not c.changed
    assert verdict_lines(c)[0].startswith("No clear change in your local usage")
    assert "plan meter is not visible" in verdict_lines(c)[2]


def test_heavy_outlier_is_removed_in_sensitivity_check(projects):
    rng = np.random.default_rng(3)
    _period_sessions(projects, BEFORE[0], 20, 100_000, rng, noise=0.05)
    _period_sessions(projects, AFTER[0], 20, 100_000, rng, noise=0.05)
    heavy = Session(projects)
    at = datetime(2026, 10, 27, 12, tzinfo=UTC)
    heavy.user(at).request(at, cache_read=80_000_000)
    heavy.write()
    c = _compare(projects)
    assert c.trimmed_after.removed == 2  # ceil(21 * 5%)
    assert c.trimmed_before.removed == 1
    assert c.metrics[0].change > 50  # the outlier inflates the raw number
    assert abs(c.trimmed_metrics[0].change) < 10
    assert not c.trimmed_changed


def test_cache_shares_are_reported_in_points(projects):
    rng = np.random.default_rng(4)
    _period_sessions(projects, BEFORE[0], 10, 100_000, rng)
    _period_sessions(projects, AFTER[0], 10, 100_000, rng)
    c = _compare(projects)
    cr, cw = c.metrics[1], c.metrics[2]
    assert cr.kind == cw.kind == "share"
    assert 0.9 < cr.before < 1.0
    assert math.isclose(cr.change, (cr.after - cr.before) * 100)


def test_same_seed_same_intervals(projects):
    rng = np.random.default_rng(5)
    _period_sessions(projects, BEFORE[0], 8, 100_000, rng)
    _period_sessions(projects, AFTER[0], 8, 120_000, rng)
    a, b = _compare(projects, seed=7), _compare(projects, seed=7)
    assert a.metrics[0].change_ci == b.metrics[0].change_ci


def test_empty_or_tiny_periods_warn_instead_of_crashing(projects):
    rng = np.random.default_rng(6)
    _period_sessions(projects, AFTER[0], 3, 100_000, rng)
    c = _compare(projects)
    assert c.before.sessions == 0
    assert any("before period has no sessions" in w for w in c.warnings)
    assert any("only 3 session" in w for w in c.warnings)
    assert math.isnan(c.metrics[0].change)
    assert "Not enough data" in verdict_lines(c)[0]


def test_sessions_spanning_periods_are_split_by_request_time(projects):
    s = Session(projects)
    t1 = datetime(2026, 10, 16, 22, tzinfo=UTC)
    t2 = datetime(2026, 10, 24, 9, tzinfo=UTC)
    s.user(t1).request(t1, cache_read=10_000).user(t2).request(t2, cache_read=20_000)
    s.write()
    c = _compare(projects)
    assert c.before.sessions == 1 and c.after.sessions == 1
    assert c.before.tokens < c.after.tokens
