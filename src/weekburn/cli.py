"""Command line interface: `weekburn report` and `weekburn compare`."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from . import __version__
from .analyze import build_comparison, build_report
from .parse import Dataset, default_project_dirs, load
from .render import fmt_day, markdown_compare, markdown_report, print_compare, print_report
from .timeutil import parse_range, parse_since, range_window

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "See which Claude Code sessions burned your weekly limit, which known causes explain it, "
        "and whether your usage per message really changed. Reads local transcripts only; "
        "makes no network calls."
    ),
)

_PROJECTS_HELP = (
    "Folder with Claude Code transcripts. Can be given more than once. "
    "Default: ~/.claude/projects and ~/.config/claude/projects (or $CLAUDE_CONFIG_DIR/projects)."
)
_MARKDOWN_HELP = "Print Markdown to paste into a GitHub issue (counts only: no prompts, paths or code)."


def _version(value: bool) -> None:
    if value:
        typer.echo(f"weekburn {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    """WeekBurn reads ~/.claude/projects and reports token use per session."""


def _fail(message: str) -> None:
    Console(stderr=True).print(f"[red]Error:[/red] {message}", highlight=False)
    raise typer.Exit(code=1)


def _dirs(projects_dir: Optional[List[Path]]) -> List[Path]:
    if projects_dir:
        dirs = [p.expanduser() for p in projects_dir]
        missing = [str(d) for d in dirs if not d.is_dir()]
        if missing:
            _fail(f"folder not found: {', '.join(missing)}")
        return dirs
    dirs = default_project_dirs()
    if not dirs:
        _fail("no Claude Code transcripts found in ~/.claude/projects. Use --projects-dir to point at them.")
    return dirs


def _load(dirs: List[Path], since: datetime) -> Dataset:
    with Console(stderr=True).status("Reading transcripts...", spinner="dots"):
        return load(dirs, modified_since=since)


@app.command()
def report(
    since: str = typer.Option("7d", "--since", help="How far back: 7d, 48h, 2w, or a date like 2026-10-20."),
    top: int = typer.Option(10, "--top", min=1, help="How many sessions to list."),
    markdown: bool = typer.Option(False, "--markdown", help=_MARKDOWN_HELP),
    projects_dir: Optional[List[Path]] = typer.Option(None, "--projects-dir", help=_PROJECTS_HELP, show_default=False),
) -> None:
    """Top sessions by tokens, their cause tags, and the share of tokens by cause."""
    now = datetime.now(timezone.utc)
    try:
        start = parse_since(since, now)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--since") from None
    data = _load(_dirs(projects_dir), start)
    rep = build_report(data, start, now, top=top)
    if not any(s.total for s in rep.sessions):
        _fail(f"no Claude Code usage found between {fmt_day(start)} and {fmt_day(now)}.")
    if markdown:
        sys.stdout.write(markdown_report(rep))
    else:
        print_report(rep, Console())


@app.command()
def compare(
    before: str = typer.Option(..., "--before", help="First period as FIRST:LAST, e.g. 2026-10-10:2026-10-16."),
    after: str = typer.Option(..., "--after", help="Second period as FIRST:LAST, e.g. 2026-10-24:2026-10-30."),
    markdown: bool = typer.Option(False, "--markdown", help=_MARKDOWN_HELP),
    resamples: int = typer.Option(2000, "--resamples", min=200, help="Bootstrap resamples."),
    seed: int = typer.Option(0, "--seed", help="Random seed, so the same data gives the same intervals."),
    projects_dir: Optional[List[Path]] = typer.Option(None, "--projects-dir", help=_PROJECTS_HELP, show_default=False),
) -> None:
    """Did tokens per user message really change between two periods? Bootstrap 95% intervals."""
    try:
        before_days = parse_range(before)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--before") from None
    try:
        after_days = parse_range(after)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--after") from None
    bw, aw = range_window(before_days), range_window(after_days)
    data = _load(_dirs(projects_dir), min(bw[0], aw[0]))
    result = build_comparison(data, before_days, after_days, bw, aw, resamples=resamples, seed=seed)
    if result.before.sessions == 0 and result.after.sessions == 0:
        _fail("no Claude Code usage found in either period.")
    if markdown:
        sys.stdout.write(markdown_compare(result))
    else:
        print_compare(result, Console())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
