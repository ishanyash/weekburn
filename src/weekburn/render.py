"""Terminal (Rich) and Markdown output.

Markdown output is meant to be pasted into a public GitHub issue. It contains counts,
dates, model names and short random session ids only: never prompt text, file paths,
project names or code.
"""

from __future__ import annotations

import math
from datetime import datetime

from . import __version__
from .analyze import TAG_RULES, Comparison, Metric, Report

REPO_URL = "https://github.com/ishanyash/weekburn"

PLAN_NOTE = (
    "Token counts are not plan usage. Anthropic does not publish how the plan meter weights "
    "input, output, cache write and cache read tokens, so the share of your weekly limit "
    "is not visible in local files."
)


# ------------------------------------------------------------------------ formatting


def fmt_tokens(n: float) -> str:
    n = float(n)
    if math.isnan(n):
        return "n/a"
    a = abs(n)
    if a < 1_000:
        return f"{n:.0f}"
    if a < 1_000_000:
        return f"{n / 1_000:.1f}k"
    if a < 1_000_000_000:
        return f"{n / 1_000_000:.2f}M"
    return f"{n / 1_000_000_000:.2f}B"


def fmt_pct(x: float, digits: int = 1) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x * 100:.{digits}f}%"


def fmt_signed(x: float, unit: str) -> str:
    return "n/a" if math.isnan(x) else f"{x:+.1f}{unit}"


def short_id(session_id: str) -> str:
    return session_id[:8]


def fmt_day(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%Y-%m-%d") if dt else "-"


def metric_value(m: Metric, value: float) -> str:
    return fmt_tokens(value) if m.kind == "ratio" else fmt_pct(value)


def metric_ci(m: Metric, ci: tuple[float, float]) -> str:
    lo, hi = ci
    if math.isnan(lo) or math.isnan(hi):
        return "n/a"
    return f"{metric_value(m, lo)} to {metric_value(m, hi)}"


def change_text(m: Metric) -> str:
    unit = "%" if m.kind == "ratio" else " pts"
    return fmt_signed(m.change, unit)


def change_ci_text(m: Metric) -> str:
    lo, hi = m.change_ci
    unit = "%" if m.kind == "ratio" else " pts"
    if math.isnan(lo) or math.isnan(hi):
        return "n/a"
    return f"{lo:+.1f}{unit} to {hi:+.1f}{unit}"


def verdict_lines(c: Comparison) -> list[str]:
    tpm = c.metrics[0]
    if math.isnan(tpm.change_ci[0]):
        head = "Not enough data to tell whether your usage per message changed."
    elif c.changed:
        direction = "up" if tpm.change > 0 else "down"
        head = (
            f"Your usage per message changed: tokens per user message went {direction} "
            f"{abs(tpm.change):.0f}% (95% interval {change_ci_text(tpm)})."
        )
    else:
        head = (
            "No clear change in your local usage: the 95% interval for tokens per user message "
            f"({change_ci_text(tpm)}) includes zero."
        )
    t = c.trimmed_metrics[0]
    removed = c.trimmed_before.removed + c.trimmed_after.removed
    if math.isnan(t.change_ci[0]):
        tail = "Without the heaviest sessions there is not enough data to check."
    elif c.trimmed_changed == c.changed:
        tail = (
            f"Removing the top 5% heaviest sessions ({removed} in total) gives the same answer "
            f"({change_text(t)}, interval {change_ci_text(t)})."
        )
    elif c.changed and (t.change * tpm.change <= 0 or abs(t.change) < abs(tpm.change) / 2):
        tail = (
            f"But without the top 5% heaviest sessions ({removed} in total) the change shrinks to "
            f"{change_text(t)} (interval {change_ci_text(t)}), so a few heavy sessions drive much of it."
        )
    elif c.changed:
        tail = (
            f"Without the top 5% heaviest sessions ({removed} in total) the change is similar "
            f"({change_text(t)}) but its interval ({change_ci_text(t)}) includes zero, so treat it as borderline."
        )
    else:
        tail = (
            f"Without the top 5% heaviest sessions ({removed} in total) there is a clear change "
            f"({change_text(t)}, interval {change_ci_text(t)}); a few heavy sessions add noise that hides it."
        )
    return [head, tail, "The plan meter is not visible in local files, so this says nothing about how Anthropic counts your limit."]


# -------------------------------------------------------------------------- markdown


def _md_table(header: list[str], rows: list[list[str]], align: list[str] | None = None) -> str:
    align = align or ["l"] + ["r"] * (len(header) - 1)
    sep = ["---:" if a == "r" else ":---" for a in align]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _md_footer() -> str:
    return (
        f"> {PLAN_NOTE}\n\n"
        f"<sub>Made with [weekburn]({REPO_URL}) v{__version__}. Counts only: no prompts, "
        "file paths or code. Local files only, nothing uploaded.</sub>\n"
    )


def markdown_report(r: Report) -> str:
    out: list[str] = []
    out.append(f"### Claude Code usage, {fmt_day(r.start)} to {fmt_day(r.end)}\n")
    out.append(
        f"{len([s for s in r.sessions if s.total])} sessions, {r.requests:,} API requests, "
        f"{r.user_messages:,} user messages, {fmt_tokens(r.total_tokens)} tokens in total.\n"
    )
    out.append("**Token types**\n")
    t = r.total_tokens or 1
    out.append(
        _md_table(
            ["Type", "Tokens", "Share"],
            [
                ["Cache read", fmt_tokens(r.cache_read_tokens), fmt_pct(r.cache_read_tokens / t)],
                ["Cache write", fmt_tokens(r.cache_write_tokens), fmt_pct(r.cache_write_tokens / t)],
                ["Input (uncached)", fmt_tokens(r.input_tokens), fmt_pct(r.input_tokens / t)],
                ["Output", fmt_tokens(r.output_tokens), fmt_pct(r.output_tokens / t)],
                ["Of all tokens, from subagents", fmt_tokens(r.subagent_tokens), fmt_pct(r.subagent_tokens / t)],
            ],
        )
        + "\n"
    )
    out.append(f"**Top {len(r.top)} sessions by tokens**\n")
    rows = []
    for i, s in enumerate(r.top, 1):
        rows.append(
            [
                str(i),
                f"`{short_id(s.session_id)}`",
                fmt_day(s.start),
                s.main_model,
                fmt_tokens(s.total),
                fmt_pct(s.total / t),
                str(s.user_messages),
                fmt_pct(s.cache_read_share, 0),
                fmt_pct(s.subagent_share, 0),
                ", ".join(s.tags) or "-",
            ]
        )
    out.append(
        _md_table(
            ["#", "Session", "Started", "Model", "Tokens", "Share", "Msgs", "Cache read", "Subagent", "Tags"],
            rows,
            ["r", "l", "l", "l", "r", "r", "r", "r", "r", "l"],
        )
        + "\n"
    )
    out.append("**Share of tokens by cause** (a session can have several tags, so shares overlap)\n")
    out.append(
        _md_table(
            ["Cause", "Sessions", "Tokens", "Share of all tokens"],
            [[c.cause, str(c.sessions), fmt_tokens(c.tokens), fmt_pct(c.share)] for c in r.causes],
        )
        + "\n"
    )
    rules = [f"- **{k}**: {v}" for k, v in TAG_RULES.items() if k != "high effort" or r.effort_recorded]
    if not r.effort_recorded:
        rules.append("- **high effort**: not shown, because these transcripts do not record effort")
    out.append("<details><summary>How tags are given</summary>\n\n" + "\n".join(rules) + "\n\n</details>\n")
    out.append(_md_footer())
    return "\n".join(out)


def markdown_compare(c: Comparison) -> str:
    out: list[str] = []
    b, a = c.before, c.after
    out.append(
        f"### Claude Code usage per message: {b.first_day} to {b.last_day} vs {a.first_day} to {a.last_day}\n"
    )
    verdict = verdict_lines(c)
    out.append(f"**{verdict[0]}**\n")
    out.append(verdict[1] + "\n")
    out.append(verdict[2] + "\n")
    out.append(
        _md_table(
            ["", "Before", "After"],
            [
                ["Days", f"{b.first_day} to {b.last_day}", f"{a.first_day} to {a.last_day}"],
                ["Sessions", str(b.sessions), str(a.sessions)],
                ["User messages", f"{b.user_messages:,}", f"{a.user_messages:,}"],
                ["Tokens", fmt_tokens(b.tokens), fmt_tokens(a.tokens)],
            ],
        )
        + "\n"
    )
    out.append("**All sessions** (95% bootstrap intervals over sessions)\n")
    out.append(_md_metrics(c.metrics) + "\n")
    out.append(
        f"**Without the top 5% heaviest sessions** ({c.trimmed_before.removed} removed before, "
        f"{c.trimmed_after.removed} removed after)\n"
    )
    out.append(_md_metrics(c.trimmed_metrics) + "\n")
    if c.warnings:
        out.append("\n".join(f"- {w}" for w in c.warnings) + "\n")
    out.append(
        f"<sub>Bootstrap: {c.resamples:,} resamples of sessions, seed {c.seed}. "
        "User messages are prompts you typed. Tool results, subagent prompts and system notes are not counted.</sub>\n"
    )
    out.append(_md_footer())
    return "\n".join(out)


def _md_metrics(metrics: list[Metric]) -> str:
    rows = [
        [
            m.name,
            f"{metric_value(m, m.before)} ({metric_ci(m, m.before_ci)})",
            f"{metric_value(m, m.after)} ({metric_ci(m, m.after_ci)})",
            f"{change_text(m)} ({change_ci_text(m)})",
        ]
        for m in metrics
    ]
    return _md_table(["Metric", "Before (95% CI)", "After (95% CI)", "Change (95% CI)"], rows)


# -------------------------------------------------------------------------- terminal


def print_report(r: Report, console) -> None:
    from rich import box
    from rich.markup import escape
    from rich.table import Table

    t = r.total_tokens or 1
    n_sessions = len([s for s in r.sessions if s.total])
    console.print(
        f"[bold]WeekBurn[/bold]  {fmt_day(r.start)} to {fmt_day(r.end)}   "
        f"{n_sessions} sessions, {r.requests:,} requests, {r.user_messages:,} user messages, "
        f"[bold]{fmt_tokens(r.total_tokens)}[/bold] tokens",
        highlight=False,
    )
    console.print(
        f"Cache read {fmt_pct(r.cache_read_tokens / t)}  ·  cache write {fmt_pct(r.cache_write_tokens / t)}  ·  "
        f"input {fmt_pct(r.input_tokens / t)}  ·  output {fmt_pct(r.output_tokens / t)}  ·  "
        f"from subagents {fmt_pct(r.subagent_tokens / t)}",
        style="dim",
        highlight=False,
    )

    table = Table(title=f"Top {len(r.top)} sessions by tokens", box=box.SIMPLE_HEAVY, title_justify="left")
    for col, just in [
        ("#", "right"), ("Session", "left"), ("Project", "left"), ("Started", "left"), ("Model", "left"),
        ("Tokens", "right"), ("Share", "right"), ("Msgs", "right"), ("Cache read", "right"),
        ("Subagent", "right"), ("Tags", "left"),
    ]:
        table.add_column(
            col,
            justify=just,
            no_wrap=col not in ("Tags", "Project"),
            min_width=14 if col == "Tags" else None,
            max_width=18 if col == "Project" else None,
        )
    for i, s in enumerate(r.top, 1):
        table.add_row(
            str(i), short_id(s.session_id), escape(s.project) or "-", fmt_day(s.start), escape(s.main_model),
            fmt_tokens(s.total), fmt_pct(s.total / t), str(s.user_messages),
            fmt_pct(s.cache_read_share, 0), fmt_pct(s.subagent_share, 0),
            ", ".join(s.tags) or "-",
        )
    console.print(table)

    causes = Table(title="Share of tokens by cause (tags overlap)", box=box.SIMPLE_HEAVY, title_justify="left")
    causes.add_column("Cause")
    causes.add_column("Sessions", justify="right")
    causes.add_column("Tokens", justify="right")
    causes.add_column("Share of all tokens", justify="right")
    for c in r.causes:
        causes.add_row(c.cause, str(c.sessions), fmt_tokens(c.tokens), fmt_pct(c.share))
    console.print(causes)
    if not r.effort_recorded:
        console.print("No effort level is recorded in these transcripts, so the high effort tag is off.", style="dim")
    console.print(PLAN_NOTE, style="dim", highlight=False)


def print_compare(c: Comparison, console) -> None:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    b, a = c.before, c.after
    head = Table(box=box.SIMPLE_HEAVY, title="Periods", title_justify="left")
    head.add_column("")
    head.add_column("Before", justify="right")
    head.add_column("After", justify="right")
    head.add_row("Days", f"{b.first_day} to {b.last_day}", f"{a.first_day} to {a.last_day}")
    head.add_row("Sessions", str(b.sessions), str(a.sessions))
    head.add_row("User messages", f"{b.user_messages:,}", f"{a.user_messages:,}")
    head.add_row("Tokens", fmt_tokens(b.tokens), fmt_tokens(a.tokens))
    console.print(head)

    for title, metrics in (
        ("All sessions (95% bootstrap intervals over sessions)", c.metrics),
        (
            f"Without the top 5% heaviest sessions ({c.trimmed_before.removed} removed before, "
            f"{c.trimmed_after.removed} removed after)",
            c.trimmed_metrics,
        ),
    ):
        t = Table(box=box.SIMPLE_HEAVY, title=title, title_justify="left")
        t.add_column("Metric")
        t.add_column("Before", justify="right")
        t.add_column("After", justify="right")
        t.add_column("Change", justify="right")
        for m in metrics:
            change = f"[bold]{change_text(m)}[/bold]" if m.clear_change else change_text(m)
            t.add_row(
                m.name,
                f"{metric_value(m, m.before)}\n[dim]{metric_ci(m, m.before_ci)}[/dim]",
                f"{metric_value(m, m.after)}\n[dim]{metric_ci(m, m.after_ci)}[/dim]",
                f"{change}\n[dim]{change_ci_text(m)}[/dim]",
            )
        console.print(t)

    for w in c.warnings:
        console.print(f"Warning: {w}", style="yellow", highlight=False)
    lines = verdict_lines(c)
    console.print(Panel(f"[bold]{lines[0]}[/bold]\n{lines[1]}\n[dim]{lines[2]}[/dim]", title="Verdict", expand=False))
    console.print(PLAN_NOTE, style="dim", highlight=False)
