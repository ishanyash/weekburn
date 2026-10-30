"""Session totals, cause tags, the weekly report and the two-period comparison."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from .parse import Dataset, Request, UserMessage

# Cause tag rules. Each tag is only given when the data supports it.
HEAVY_TOP_FRACTION = 0.05  # top 5% of sessions by tokens
SUBAGENT_SHARE = 0.50  # more than half the session's tokens came from subagents
IDLE_MINUTES = 60.0  # a request after more than an hour of silence ...
IDLE_UNCACHED_TOKENS = 100_000  # ... that sent over 100k tokens not served from cache
LONG_CONTEXT_MEDIAN = 150_000  # median prompt size of the main conversation
HIGH_EFFORT_LEVELS = frozenset({"xhigh", "max"})
HIGH_EFFORT_SHARE = 0.50  # more than half the session's tokens at xhigh or max effort

TAG_HEAVY = "heavy session"
TAG_SUBAGENT = "subagent heavy"
TAG_IDLE = "idle resume"
TAG_LONG = "long context"
TAG_EFFORT = "high effort"
TAG_ORDER = [TAG_HEAVY, TAG_SUBAGENT, TAG_IDLE, TAG_LONG, TAG_EFFORT]

TAG_RULES = {
    TAG_HEAVY: "top 5% of sessions by total tokens in the period",
    TAG_SUBAGENT: "over 50% of the session's tokens came from subagents",
    TAG_IDLE: "a request after more than 60 minutes idle that sent over 100k uncached tokens",
    TAG_LONG: "median prompt size of the main conversation over 150k tokens",
    TAG_EFFORT: "over 50% of the session's tokens at xhigh or max effort (only when effort is recorded)",
}


def top_count(n: int, fraction: float = HEAVY_TOP_FRACTION) -> int:
    """How many sessions make up the top ``fraction``. At least one when n > 0."""
    return math.ceil(n * fraction) if n > 0 else 0


@dataclass
class SessionStats:
    session_id: str
    project: str = ""
    start: datetime | None = None
    end: datetime | None = None
    requests: int = 0
    user_messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    subagent_tokens: int = 0
    high_effort_tokens: int = 0
    idle_resumes: int = 0
    median_context: float = 0.0
    models: Counter = field(default_factory=Counter)
    tags: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def subagent_share(self) -> float:
        return self.subagent_tokens / self.total if self.total else 0.0

    @property
    def cache_read_share(self) -> float:
        return self.cache_read_tokens / self.total if self.total else 0.0

    @property
    def main_model(self) -> str:
        return self.models.most_common(1)[0][0] if self.models else "unknown"


def in_window(items, start: datetime | None, end: datetime | None):
    return [x for x in items if (start is None or x.timestamp >= start) and (end is None or x.timestamp < end)]


def session_stats(requests: list[Request], user_messages: list[UserMessage]) -> list[SessionStats]:
    """Aggregate requests and user messages into one row per session."""
    rows: dict[str, SessionStats] = {}
    contexts: dict[str, list[int]] = {}
    sub_contexts: dict[str, list[int]] = {}
    for r in requests:
        s = rows.get(r.session_id)
        if s is None:
            s = rows[r.session_id] = SessionStats(session_id=r.session_id)
        s.requests += 1
        s.input_tokens += r.input_tokens
        s.output_tokens += r.output_tokens
        s.cache_write_tokens += r.cache_write_tokens
        s.cache_read_tokens += r.cache_read_tokens
        s.models[r.model] += r.total
        if r.is_subagent:
            s.subagent_tokens += r.total
            sub_contexts.setdefault(r.session_id, []).append(r.context)
        else:
            contexts.setdefault(r.session_id, []).append(r.context)
            if r.project and not s.project:
                s.project = r.project
        if r.effort in HIGH_EFFORT_LEVELS:
            s.high_effort_tokens += r.total
        if (
            r.gap_minutes is not None
            and r.gap_minutes > IDLE_MINUTES
            and r.uncached > IDLE_UNCACHED_TOKENS
        ):
            s.idle_resumes += 1
        if s.start is None or r.timestamp < s.start:
            s.start = r.timestamp
        if s.end is None or r.timestamp > s.end:
            s.end = r.timestamp
    for u in user_messages:
        s = rows.get(u.session_id)
        if s is None:
            s = rows[u.session_id] = SessionStats(session_id=u.session_id, start=u.timestamp, end=u.timestamp)
        s.user_messages += 1
    for sid, s in rows.items():
        ctx = contexts.get(sid) or sub_contexts.get(sid) or []
        s.median_context = float(statistics.median(ctx)) if ctx else 0.0
    return list(rows.values())


def apply_tags(sessions: list[SessionStats], effort_recorded: bool) -> None:
    ranked = sorted((s for s in sessions if s.total > 0), key=lambda s: s.total, reverse=True)
    heavy = {s.session_id for s in ranked[: top_count(len(ranked))]}
    for s in sessions:
        tags: list[str] = []
        if s.session_id in heavy:
            tags.append(TAG_HEAVY)
        if s.subagent_share > SUBAGENT_SHARE:
            tags.append(TAG_SUBAGENT)
        if s.idle_resumes > 0:
            tags.append(TAG_IDLE)
        if s.median_context > LONG_CONTEXT_MEDIAN:
            tags.append(TAG_LONG)
        if effort_recorded and s.total and s.high_effort_tokens / s.total > HIGH_EFFORT_SHARE:
            tags.append(TAG_EFFORT)
        s.tags = tags


# --------------------------------------------------------------------------- report


@dataclass
class CauseRow:
    cause: str
    sessions: int
    tokens: int
    share: float


@dataclass
class Report:
    start: datetime
    end: datetime
    sessions: list[SessionStats]  # all sessions in the window, heaviest first
    top: list[SessionStats]
    causes: list[CauseRow]
    total_tokens: int
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    subagent_tokens: int
    requests: int
    user_messages: int
    idle_resume_requests: int
    effort_recorded: bool


def build_report(data: Dataset, start: datetime, end: datetime, top: int = 10) -> Report:
    reqs = in_window(data.requests, start, end)
    msgs = in_window(data.user_messages, start, end)
    sessions = session_stats(reqs, msgs)
    effort_recorded = any(r.effort for r in reqs)
    apply_tags(sessions, effort_recorded)
    sessions.sort(key=lambda s: s.total, reverse=True)
    total = sum(s.total for s in sessions)

    causes: list[CauseRow] = []
    for tag in TAG_ORDER:
        if tag == TAG_EFFORT and not effort_recorded:
            continue
        tagged = [s for s in sessions if tag in s.tags]
        tok = sum(s.total for s in tagged)
        causes.append(CauseRow(tag, len(tagged), tok, tok / total if total else 0.0))
    untagged = [s for s in sessions if not s.tags and s.total > 0]
    tok = sum(s.total for s in untagged)
    causes.append(CauseRow("no tag", len(untagged), tok, tok / total if total else 0.0))

    return Report(
        start=start,
        end=end,
        sessions=sessions,
        top=sessions[:top],
        causes=causes,
        total_tokens=total,
        input_tokens=sum(s.input_tokens for s in sessions),
        output_tokens=sum(s.output_tokens for s in sessions),
        cache_write_tokens=sum(s.cache_write_tokens for s in sessions),
        cache_read_tokens=sum(s.cache_read_tokens for s in sessions),
        subagent_tokens=sum(s.subagent_tokens for s in sessions),
        requests=len(reqs),
        user_messages=len(msgs),
        idle_resume_requests=sum(s.idle_resumes for s in sessions),
        effort_recorded=effort_recorded,
    )


# -------------------------------------------------------------------------- compare

METRIC_TPM = "Tokens per user message"
METRIC_CR = "Cache read share"
METRIC_CW = "Cache write share"
MIN_SESSIONS = 5


@dataclass
class Metric:
    name: str
    kind: str  # "ratio" (change shown in %) or "share" (change shown in points)
    before: float
    before_ci: tuple[float, float]
    after: float
    after_ci: tuple[float, float]
    change: float  # % change for ratio metrics, percentage points for shares
    change_ci: tuple[float, float]

    @property
    def clear_change(self) -> bool:
        lo, hi = self.change_ci
        if math.isnan(lo) or math.isnan(hi):
            return False
        return lo > 0 or hi < 0


@dataclass
class Period:
    label: str
    first_day: date
    last_day: date
    sessions: int
    user_messages: int
    tokens: int
    removed: int = 0  # sessions dropped by the heavy-session check


@dataclass
class Comparison:
    before: Period
    after: Period
    metrics: list[Metric]
    trimmed_before: Period
    trimmed_after: Period
    trimmed_metrics: list[Metric]
    resamples: int
    seed: int
    warnings: list[str]

    @property
    def changed(self) -> bool:
        return self.metrics[0].clear_change

    @property
    def trimmed_changed(self) -> bool:
        return self.trimmed_metrics[0].clear_change


def _session_matrix(sessions: list[SessionStats]) -> np.ndarray:
    """Columns: total tokens, user messages, cache read tokens, cache write tokens."""
    if not sessions:
        return np.zeros((0, 4), dtype=float)
    return np.array(
        [[s.total, s.user_messages, s.cache_read_tokens, s.cache_write_tokens] for s in sessions],
        dtype=float,
    )


def _metrics_from_sums(sums: np.ndarray) -> np.ndarray:
    """sums has shape (..., 4); returns (..., 3): tokens/msg, cache read share, cache write share."""
    tok, msg, cr, cw = (sums[..., i] for i in range(4))
    with np.errstate(divide="ignore", invalid="ignore"):
        tpm = np.where(msg > 0, tok / np.where(msg > 0, msg, 1), np.nan)
        crs = np.where(tok > 0, cr / np.where(tok > 0, tok, 1), np.nan)
        cws = np.where(tok > 0, cw / np.where(tok > 0, tok, 1), np.nan)
    return np.stack([tpm, crs, cws], axis=-1)


def _bootstrap_sums(mat: np.ndarray, resamples: int, rng: np.random.Generator, chunk: int = 250) -> np.ndarray:
    """Resample sessions with replacement and return the column sums of each resample."""
    n = mat.shape[0]
    if n == 0:
        return np.full((resamples, mat.shape[1]), np.nan)
    out = np.empty((resamples, mat.shape[1]))
    done = 0
    while done < resamples:
        size = min(chunk, resamples - done)
        counts = rng.multinomial(n, np.full(n, 1.0 / n), size=size)
        out[done : done + size] = counts @ mat
        done += size
    return out


def _ci(values: np.ndarray) -> tuple[float, float]:
    v = values[~np.isnan(values)]
    if v.size < 10:
        return (math.nan, math.nan)
    lo, hi = np.percentile(v, [2.5, 97.5])
    return (float(lo), float(hi))


def _compare_sessions(
    before: list[SessionStats], after: list[SessionStats], resamples: int, seed: int
) -> list[Metric]:
    rng = np.random.default_rng(seed)
    mb, ma = _session_matrix(before), _session_matrix(after)
    point_b = _metrics_from_sums(mb.sum(axis=0))
    point_a = _metrics_from_sums(ma.sum(axis=0))
    boot_b = _metrics_from_sums(_bootstrap_sums(mb, resamples, rng))
    boot_a = _metrics_from_sums(_bootstrap_sums(ma, resamples, rng))

    metrics: list[Metric] = []
    for i, (name, kind) in enumerate([(METRIC_TPM, "ratio"), (METRIC_CR, "share"), (METRIC_CW, "share")]):
        b, a = float(point_b[i]), float(point_a[i])
        with np.errstate(divide="ignore", invalid="ignore"):
            if kind == "ratio":
                change = (a / b - 1.0) * 100.0 if b and not math.isnan(b) else math.nan
                change_draws = (boot_a[:, i] / boot_b[:, i] - 1.0) * 100.0
            else:
                change = (a - b) * 100.0
                change_draws = (boot_a[:, i] - boot_b[:, i]) * 100.0
        change_draws = np.where(np.isfinite(change_draws), change_draws, np.nan)
        metrics.append(
            Metric(
                name=name,
                kind=kind,
                before=b,
                before_ci=_ci(boot_b[:, i]),
                after=a,
                after_ci=_ci(boot_a[:, i]),
                change=change,
                change_ci=_ci(change_draws),
            )
        )
    return metrics


def _drop_heaviest(sessions: list[SessionStats]) -> tuple[list[SessionStats], int]:
    if len(sessions) < 2:
        return list(sessions), 0
    k = top_count(len(sessions))
    ranked = sorted(sessions, key=lambda s: s.total, reverse=True)
    return ranked[k:], k


def _period(label: str, days: tuple[date, date], sessions: list[SessionStats], removed: int = 0) -> Period:
    return Period(
        label=label,
        first_day=days[0],
        last_day=days[1],
        sessions=len(sessions),
        user_messages=sum(s.user_messages for s in sessions),
        tokens=sum(s.total for s in sessions),
        removed=removed,
    )


def build_comparison(
    data: Dataset,
    before_days: tuple[date, date],
    after_days: tuple[date, date],
    before_window: tuple[datetime, datetime],
    after_window: tuple[datetime, datetime],
    resamples: int = 2000,
    seed: int = 0,
) -> Comparison:
    def sessions_in(window: tuple[datetime, datetime]) -> list[SessionStats]:
        reqs = in_window(data.requests, *window)
        msgs = in_window(data.user_messages, *window)
        return [s for s in session_stats(reqs, msgs) if s.total > 0 or s.user_messages > 0]

    sb, sa = sessions_in(before_window), sessions_in(after_window)
    tb, removed_b = _drop_heaviest(sb)
    ta, removed_a = _drop_heaviest(sa)

    warnings: list[str] = []
    for label, sess in (("before", sb), ("after", sa)):
        if not sess:
            warnings.append(f"The {label} period has no sessions.")
        elif len(sess) < MIN_SESSIONS:
            warnings.append(
                f"The {label} period has only {len(sess)} session(s); intervals will be wide or missing."
            )
        if sess and sum(s.user_messages for s in sess) == 0:
            warnings.append(f"The {label} period has no user messages, so tokens per message cannot be computed.")

    return Comparison(
        before=_period("before", before_days, sb),
        after=_period("after", after_days, sa),
        metrics=_compare_sessions(sb, sa, resamples, seed),
        trimmed_before=_period("before", before_days, tb, removed_b),
        trimmed_after=_period("after", after_days, ta, removed_a),
        trimmed_metrics=_compare_sessions(tb, ta, resamples, seed),
        resamples=resamples,
        seed=seed,
        warnings=warnings,
    )
