from datetime import datetime, timedelta, timezone

from conftest import Session

from weekburn.analyze import (
    TAG_EFFORT,
    TAG_HEAVY,
    TAG_IDLE,
    TAG_LONG,
    TAG_SUBAGENT,
    build_report,
    top_count,
)
from weekburn.parse import load

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
START, END = T0 - timedelta(days=1), T0 + timedelta(days=7)


def _small(projects, at=T0, **kw):
    s = Session(projects)
    s.user(at).request(at, input=5, output=100, cache_write=500, cache_read=5_000, **kw)
    s.write()
    return s


def _tags(report, session):
    return next(x.tags for x in report.sessions if x.session_id == session.session_id)


def test_top_count_rounds_up():
    assert [top_count(n) for n in (0, 1, 19, 20, 21, 100)] == [0, 1, 1, 1, 2, 5]


def test_heavy_session_is_top_five_percent(projects):
    small = [_small(projects) for _ in range(19)]
    big = Session(projects)
    big.user(T0).request(T0, cache_read=5_000_000)
    big.write()
    rep = build_report(load([projects]), START, END)
    assert TAG_HEAVY in _tags(rep, big)
    assert all(TAG_HEAVY not in _tags(rep, s) for s in small)
    assert rep.top[0].session_id == big.session_id


def test_subagent_heavy(projects):
    parent = Session(projects)
    parent.user(T0).request(T0, cache_read=10_000)
    parent.write()
    sub = Session(projects, parent=parent, agent_id="x1")
    sub.request(T0 + timedelta(seconds=10), cache_read=30_000)
    sub.write()
    rep = build_report(load([projects]), START, END)
    assert TAG_SUBAGENT in _tags(rep, parent)
    assert rep.subagent_tokens > 0


def test_idle_resume_needs_long_gap_and_large_uncached_write(projects):
    resumed = Session(projects)
    resumed.user(T0).request(T0)
    resumed.request(T0 + timedelta(minutes=61), cache_write=150_000, cache_read=0)
    resumed.write()

    warm = Session(projects)  # long gap but cache still served most of the prompt
    warm.user(T0).request(T0)
    warm.request(T0 + timedelta(minutes=61), cache_write=2_000, cache_read=150_000)
    warm.write()

    quick = Session(projects)  # big write but no idle gap
    quick.user(T0).request(T0)
    quick.request(T0 + timedelta(minutes=30), cache_write=150_000, cache_read=0)
    quick.write()

    rep = build_report(load([projects]), START, END)
    assert TAG_IDLE in _tags(rep, resumed)
    assert TAG_IDLE not in _tags(rep, warm)
    assert TAG_IDLE not in _tags(rep, quick)
    assert rep.idle_resume_requests == 1


def test_long_context_uses_main_conversation_median(projects):
    long = Session(projects)
    long.user(T0)
    for i in range(3):
        long.request(T0 + timedelta(minutes=i), cache_read=160_000)
    long.write()
    sub = Session(projects, parent=long, agent_id="small")
    for i in range(5):  # many small subagent prompts must not pull the median down
        sub.request(T0 + timedelta(minutes=i, seconds=30), cache_read=2_000)
    sub.write()
    short = Session(projects)
    short.user(T0).request(T0, cache_read=100_000)
    short.write()
    rep = build_report(load([projects]), START, END)
    assert TAG_LONG in _tags(rep, long)
    assert TAG_LONG not in _tags(rep, short)


def test_high_effort_only_when_effort_recorded(projects):
    _small(projects)
    rep = build_report(load([projects]), START, END)
    assert not rep.effort_recorded
    assert TAG_EFFORT not in [c.cause for c in rep.causes]

    hot = Session(projects)
    hot.user(T0).request(T0, effort="xhigh").request(T0 + timedelta(minutes=1), effort="xhigh")
    hot.write()
    mild = Session(projects)
    mild.user(T0).request(T0, effort="medium")
    mild.write()
    rep = build_report(load([projects]), START, END)
    assert rep.effort_recorded
    assert TAG_EFFORT in _tags(rep, hot)
    assert TAG_EFFORT not in _tags(rep, mild)
    assert TAG_EFFORT in [c.cause for c in rep.causes]


def test_report_window_top_limit_and_causes(projects):
    for i in range(15):
        _small(projects)
    _small(projects, at=T0 - timedelta(days=10))  # outside the window
    rep = build_report(load([projects]), START, END, top=10)
    assert len(rep.sessions) == 15
    assert len(rep.top) == 10
    assert rep.user_messages == 15
    assert rep.total_tokens == 15 * 5_605
    no_tag = next(c for c in rep.causes if c.cause == "no tag")
    heavy = next(c for c in rep.causes if c.cause == TAG_HEAVY)
    assert no_tag.sessions + heavy.sessions == 15
    assert abs(no_tag.share + heavy.share - 1.0) < 1e-9
