import os
from datetime import datetime, timedelta, timezone

from conftest import Session

from weekburn.parse import load, parse_files

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def test_one_record_per_request_even_when_split_into_blocks(projects):
    s = Session(projects)
    s.user(T0).request(T0, input=10, output=200, cache_write=3_000, cache_read=40_000, blocks=3).write()
    data = load([projects])
    assert len(data.requests) == 1
    r = data.requests[0]
    assert (r.input_tokens, r.output_tokens, r.cache_write_tokens, r.cache_read_tokens) == (10, 200, 3_000, 40_000)
    assert r.total == 43_210
    assert data.duplicate_lines == 2


def test_streamed_partial_keeps_largest_counts(projects):
    Session(projects).request(T0, output=900, blocks=3, partial_first=True).write()
    data = load([projects])
    assert data.requests[0].output_tokens == 900


def test_replayed_request_in_resumed_session_counted_once(projects):
    a = Session(projects).user(T0).request(T0, request_id="req_shared")
    a.write()
    b = Session(projects).request(T0, request_id="req_shared").request(T0 + timedelta(minutes=5))
    b.write()
    data = load([projects])
    assert len(data.requests) == 2
    assert sum(1 for r in data.requests if r.key == "req_shared") == 1


def test_message_id_used_when_request_id_missing(projects):
    s = Session(projects).request(T0, blocks=2)
    for rec in s.lines:
        rec.pop("requestId")
    s.write()
    assert len(load([projects]).requests) == 1


def test_subagent_file_and_inline_sidechain_are_subagent(projects):
    parent = Session(projects).user(T0).request(T0)
    parent.write()
    sub = Session(projects, parent=parent, agent_id="a1b2c3")
    sub.user(T0 + timedelta(seconds=5), text="subagent task prompt").request(T0 + timedelta(seconds=6))
    sub.write()
    inline = Session(projects).request(T0)
    for rec in inline.lines:
        rec["isSidechain"] = True
    inline.write()
    data = load([projects])
    subs = [r for r in data.requests if r.is_subagent]
    assert len(subs) == 2
    assert any(r.session_id == parent.session_id for r in subs)
    # the subagent's prompt is not a typed message
    assert len(data.user_messages) == 1


def test_typed_messages_exclude_tool_results_meta_and_local_command_output(projects):
    s = Session(projects)
    s.user(T0)
    s.tool_result(T0 + timedelta(seconds=1))
    s.meta(T0 + timedelta(seconds=2))
    s.user(T0 + timedelta(seconds=3), text="<local-command-stdout>ok</local-command-stdout>")
    s.user(T0 + timedelta(seconds=4), text="[Request interrupted by user]")
    s.user_blocks(T0 + timedelta(seconds=5), [{"type": "text", "text": "second prompt"}])
    s.user_blocks(T0 + timedelta(seconds=6), [{"type": "image", "source": {}}])
    s.write()
    data = load([projects])
    assert len(data.user_messages) == 3


def test_replayed_user_message_counted_once(projects):
    a = Session(projects).user(T0)
    a.write()
    b = Session(projects)
    b.lines.append(dict(a.lines[0], sessionId=b.session_id))
    b.write()
    assert len(load([projects]).user_messages) == 1


def test_gap_since_previous_request_in_same_session(projects):
    s = Session(projects)
    s.request(T0).request(T0 + timedelta(minutes=90)).request(T0 + timedelta(minutes=95))
    s.write()
    Session(projects).request(T0 + timedelta(minutes=91)).write()
    data = load([projects])
    mine = sorted((r for r in data.requests if r.session_id == s.session_id), key=lambda r: r.timestamp)
    assert mine[0].gap_minutes is None
    assert round(mine[1].gap_minutes) == 90
    assert round(mine[2].gap_minutes) == 5


def test_zero_usage_and_bad_lines_are_skipped(projects):
    s = Session(projects).request(T0, input=0, output=0, cache_write=0, cache_read=0)
    s.raw('{"type":"assistant","usage" this is not json')
    s.request(T0 + timedelta(minutes=1))
    s.write()
    data = load([projects])
    assert len(data.requests) == 1
    assert data.bad_lines == 1


def test_effort_recorded_only_when_present(projects):
    Session(projects).request(T0).write()
    assert not load([projects]).effort_recorded
    Session(projects).request(T0, effort="xhigh").write()
    data = load([projects])
    assert data.effort_recorded
    assert {r.effort for r in data.requests} == {None, "xhigh"}


def test_files_not_modified_since_window_are_skipped(projects):
    old = Session(projects).request(T0)
    path = old.write()
    past = (T0 - timedelta(days=30)).timestamp()
    os.utime(path, (past, past))
    Session(projects).request(T0).write()
    data = load([projects], modified_since=T0 - timedelta(days=1))
    assert data.files_read == 1


def test_project_name_is_folder_name_only(projects):
    path = Session(projects).request(T0).write()
    data = parse_files([path])
    assert data.requests[0].project == "secret-project"
    win = Session(projects, cwd="C:\\Users\\bob\\work\\shop-api\\").request(T0).write()
    assert parse_files([win]).requests[0].project == "shop-api"
