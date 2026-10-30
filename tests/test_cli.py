"""End-to-end runs of the installed command line."""

from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import SECRET_CWD, SECRET_PROMPT, Session

typer_testing = pytest.importorskip("typer.testing")

from weekburn import __version__  # noqa: E402
from weekburn.cli import app  # noqa: E402

runner = typer_testing.CliRunner()


def _recent(projects, now):
    for i in range(6):
        at = now - timedelta(days=1, hours=i)
        s = Session(projects)
        s.user(at).request(at, cache_read=60_000 * (i + 1)).tool_result(at)
        s.write()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_report_terminal(projects, now):
    _recent(projects, now)
    result = runner.invoke(app, ["report", "--since", "7d", "--projects-dir", str(projects)])
    assert result.exit_code == 0, result.output
    assert "Top 6 sessions by tokens" in result.output
    assert "Share of tokens by cause" in result.output


def test_report_markdown_is_clean(projects, now):
    _recent(projects, now)
    result = runner.invoke(app, ["report", "--since", "7d", "--markdown", "--projects-dir", str(projects)])
    assert result.exit_code == 0, result.output
    assert "| # | Session |" in result.stdout
    assert SECRET_PROMPT not in result.stdout
    assert SECRET_CWD not in result.stdout
    assert "secret-project" not in result.stdout


def test_compare_terminal_and_markdown(projects):
    for day in (date(2026, 10, 12), date(2026, 10, 26)):
        for i in range(6):
            at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9 + i)
            Session(projects).user(at).request(at, cache_read=50_000 + 1_000 * i).write()
    args = ["compare", "--before", "2026-10-10:2026-10-16", "--after", "2026-10-24:2026-10-30",
            "--projects-dir", str(projects), "--resamples", "500"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Verdict" in result.output
    assert "Without the top 5% heaviest sessions" in result.output
    md = runner.invoke(app, args + ["--markdown"])
    assert md.exit_code == 0, md.output
    assert "Tokens per user message" in md.stdout
    assert SECRET_PROMPT not in md.stdout


def test_bad_arguments_and_empty_folder(projects, tmp_path):
    assert runner.invoke(app, ["report", "--since", "soon", "--projects-dir", str(projects)]).exit_code != 0
    assert runner.invoke(app, ["compare", "--before", "x", "--after", "2026-10-24:2026-10-30"]).exit_code != 0
    empty = runner.invoke(app, ["report", "--projects-dir", str(projects)])
    assert empty.exit_code == 1
    missing = runner.invoke(app, ["report", "--projects-dir", str(tmp_path / "nope")])
    assert missing.exit_code == 1
