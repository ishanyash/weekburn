"""Markdown output must be safe to paste into a public GitHub issue."""

import re
from datetime import date, datetime, timedelta, timezone

from conftest import SECRET_CODE, SECRET_CWD, SECRET_PROJECT_DIR, SECRET_PROMPT, Session

from weekburn.analyze import build_comparison, build_report
from weekburn.parse import load
from weekburn.render import PLAN_NOTE, fmt_tokens, markdown_compare, markdown_report
from weekburn.timeutil import range_window

UTC = timezone.utc
FORBIDDEN = [SECRET_PROMPT, SECRET_CODE, SECRET_CWD, SECRET_PROJECT_DIR, "secret-project", "secret_function", "/Users/"]


def _populate(projects):
    sessions = []
    for day in (date(2026, 10, 12), date(2026, 10, 26)):
        for i in range(6):
            at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9 + i)
            s = Session(projects)
            s.user(at).request(at, cache_read=40_000 * (i + 1), effort="xhigh").tool_result(at)
            s.user(at + timedelta(minutes=1), text=SECRET_PROMPT + " again")
            s.request(at + timedelta(minutes=1), cache_read=50_000)
            s.write()
            sub = Session(projects, parent=s, agent_id=f"ag{i}")
            sub.user(at, text=SECRET_PROMPT).request(at + timedelta(seconds=30))
            sub.write()
            sessions.append(s)
    return sessions


def _assert_clean(md: str):
    for bad in FORBIDDEN:
        assert bad not in md, f"leaked {bad!r}"
    # no absolute paths of any kind outside of the repo link
    without_links = re.sub(r"https?://\S+", "", md)
    assert not re.search(r"(^|\s)(/|~/|[A-Za-z]:\\)\w", without_links)


def test_report_markdown_has_counts_only(projects):
    sessions = _populate(projects)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    rep = build_report(load([projects]), start, start + timedelta(days=40))
    md = markdown_report(rep)
    _assert_clean(md)
    assert PLAN_NOTE in md
    assert "| # | Session |" in md
    assert any(s.session_id[:8] in md for s in sessions)
    assert fmt_tokens(rep.total_tokens) in md
    assert "high effort" in md


def test_compare_markdown_has_counts_only(projects):
    _populate(projects)
    b, a = (date(2026, 10, 10), date(2026, 10, 16)), (date(2026, 10, 24), date(2026, 10, 30))
    c = build_comparison(load([projects]), b, a, range_window(b, UTC), range_window(a, UTC), resamples=500)
    md = markdown_compare(c)
    _assert_clean(md)
    assert PLAN_NOTE in md
    assert "Tokens per user message" in md
    assert "Without the top 5% heaviest sessions" in md
    assert "plan meter is not visible" in md
