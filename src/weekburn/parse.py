"""Read Claude Code transcripts and turn them into one usage record per API request.

Claude Code writes one JSON object per line to ~/.claude/projects/<project>/<session>.jsonl.
A single API request is usually written as several "assistant" lines (one per content
block: thinking, text, each tool call), and every one of those lines repeats the same
usage block. Summing every line therefore counts the same request two to eight times.
We keep one record per request id (falling back to the message id).

Subagent work is either written inline with "isSidechain": true, or to a separate file
under <project>/<session>/subagents/. Both are attributed to the parent session.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Lines that start like this are tool output or bookkeeping that Claude Code stores as
# "user" records. They are not messages a person typed.
_NOT_TYPED_PREFIXES = (
    "<local-command-stdout>",
    "<local-command-stderr>",
    "[Request interrupted",
    "Caveat:",
)


@dataclass(slots=True)
class Request:
    """Token usage of one API request."""

    key: str
    session_id: str
    timestamp: datetime
    model: str
    is_subagent: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    effort: str | None = None
    project: str = ""
    gap_minutes: float | None = None

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def context(self) -> int:
        """Size of the prompt sent with this request (cached and uncached)."""
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def uncached(self) -> int:
        """Prompt tokens that were not served from cache."""
        return self.input_tokens + self.cache_write_tokens


@dataclass(slots=True)
class UserMessage:
    key: str
    session_id: str
    timestamp: datetime


@dataclass
class Dataset:
    requests: list[Request] = field(default_factory=list)
    user_messages: list[UserMessage] = field(default_factory=list)
    files_read: int = 0
    lines_read: int = 0
    duplicate_lines: int = 0
    bad_lines: int = 0

    @property
    def effort_recorded(self) -> bool:
        return any(r.effort for r in self.requests)


def default_project_dirs() -> list[Path]:
    """Folders where Claude Code keeps transcripts on this machine."""
    env = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if env:
        candidates = [Path(p).expanduser() / "projects" for p in env.split(",") if p.strip()]
    else:
        home = Path.home()
        candidates = [home / ".claude" / "projects", home / ".config" / "claude" / "projects"]
    seen: list[Path] = []
    for c in candidates:
        if c.is_dir() and c.resolve() not in [s.resolve() for s in seen]:
            seen.append(c)
    return seen


def find_transcripts(dirs: Iterable[Path], modified_since: datetime | None = None) -> list[Path]:
    """All .jsonl files under the given folders, oldest-unmodified files skipped."""
    cutoff = modified_since.timestamp() if modified_since else None
    files: list[Path] = []
    for d in dirs:
        for p in Path(d).rglob("*.jsonl"):
            try:
                if cutoff is not None and p.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            files.append(p)
    return sorted(set(files))


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _folder_name(cwd: object) -> str:
    """Last part of a working directory, for Windows and POSIX paths alike."""
    if not isinstance(cwd, str) or not cwd:
        return ""
    return re.split(r"[\\/]", cwd.rstrip("\\/"))[-1]


def _message_text(content: object) -> tuple[bool, str]:
    """Return (is_typed_message, text) for the content of a "user" record."""
    if isinstance(content, str):
        return True, content
    if not isinstance(content, list):
        return False, ""
    texts: list[str] = []
    has_input = False
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "tool_result":
            return False, ""
        if kind == "text":
            has_input = True
            texts.append(str(block.get("text", "")))
        elif kind in ("image", "document"):
            has_input = True
    return has_input, " ".join(texts)


def load(dirs: Iterable[Path] | None = None, modified_since: datetime | None = None) -> Dataset:
    """Parse every transcript under ``dirs`` into a deduplicated Dataset."""
    dirs = list(dirs) if dirs is not None else default_project_dirs()
    files = find_transcripts(dirs, modified_since)
    return parse_files(files)


def parse_files(files: Iterable[Path]) -> Dataset:
    data = Dataset()
    by_key: dict[str, Request] = {}
    users: dict[str, UserMessage] = {}

    for path in files:
        data.files_read += 1
        in_subagent_dir = "subagents" in path.parts
        try:
            fh = open(path, "rb")
        except OSError:
            continue
        with fh:
            for raw in fh:
                data.lines_read += 1
                # Cheap byte checks first: most bytes in a transcript are tool output.
                if b'"assistant"' in raw and b'"usage"' in raw:
                    pass
                elif b'"user"' in raw and b'"tool_result"' not in raw:
                    pass
                else:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    data.bad_lines += 1
                    continue
                if not isinstance(rec, dict):
                    continue
                kind = rec.get("type")
                if kind == "assistant":
                    _add_request(rec, path, in_subagent_dir, by_key, data)
                elif kind == "user":
                    _add_user_message(rec, path, in_subagent_dir, users)

    requests = sorted(by_key.values(), key=lambda r: (r.session_id, r.timestamp))
    prev: Request | None = None
    for r in requests:
        if prev is not None and prev.session_id == r.session_id:
            r.gap_minutes = (r.timestamp - prev.timestamp).total_seconds() / 60.0
        prev = r
    requests.sort(key=lambda r: r.timestamp)
    data.requests = requests
    data.user_messages = sorted(users.values(), key=lambda u: u.timestamp)
    return data


def _add_request(
    rec: dict, path: Path, in_subagent_dir: bool, by_key: dict[str, Request], data: Dataset
) -> None:
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return
    inp = _int(usage.get("input_tokens"))
    out = _int(usage.get("output_tokens"))
    cw = _int(usage.get("cache_creation_input_tokens"))
    cr = _int(usage.get("cache_read_input_tokens"))
    if inp + out + cw + cr == 0:
        return  # placeholder or synthetic record, no API call behind it
    ts = parse_timestamp(rec.get("timestamp"))
    if ts is None:
        return
    key = rec.get("requestId") or msg.get("id") or rec.get("uuid")
    if not isinstance(key, str) or not key:
        return
    session = rec.get("sessionId") if isinstance(rec.get("sessionId"), str) else None
    session = session or path.stem
    is_sub = bool(rec.get("isSidechain")) or in_subagent_dir or bool(rec.get("agentId"))
    effort = rec.get("effort") or rec.get("perTurnEffort")
    effort = effort.lower() if isinstance(effort, str) and effort else None
    model = msg.get("model") or rec.get("requestedModel") or "unknown"
    cwd = rec.get("cwd")
    project = _folder_name(cwd)

    existing = by_key.get(key)
    if existing is None:
        by_key[key] = Request(
            key=key,
            session_id=session,
            timestamp=ts,
            model=str(model),
            is_subagent=is_sub,
            input_tokens=inp,
            output_tokens=out,
            cache_write_tokens=cw,
            cache_read_tokens=cr,
            effort=effort,
            project=project,
        )
        return

    # Same request seen again: another content block of the same response, a streamed
    # partial, or a copy replayed into a resumed session. Keep the largest counts.
    data.duplicate_lines += 1
    existing.input_tokens = max(existing.input_tokens, inp)
    existing.output_tokens = max(existing.output_tokens, out)
    existing.cache_write_tokens = max(existing.cache_write_tokens, cw)
    existing.cache_read_tokens = max(existing.cache_read_tokens, cr)
    if ts < existing.timestamp:
        existing.timestamp = ts
    existing.effort = existing.effort or effort


def _add_user_message(
    rec: dict, path: Path, in_subagent_dir: bool, users: dict[str, UserMessage]
) -> None:
    if rec.get("isMeta") or rec.get("isSidechain") or in_subagent_dir or rec.get("agentId"):
        return
    if "toolUseResult" in rec:
        return
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return
    typed, text = _message_text(msg.get("content"))
    if not typed:
        return
    if text.lstrip().startswith(_NOT_TYPED_PREFIXES):
        return
    ts = parse_timestamp(rec.get("timestamp"))
    if ts is None:
        return
    session = rec.get("sessionId") if isinstance(rec.get("sessionId"), str) else None
    session = session or path.stem
    key = rec.get("uuid") if isinstance(rec.get("uuid"), str) else f"{session}:{ts.isoformat()}"
    if key not in users:
        users[key] = UserMessage(key=key, session_id=session, timestamp=ts)
