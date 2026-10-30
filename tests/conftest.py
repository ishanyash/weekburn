"""Builders for small synthetic transcripts that follow the real Claude Code layout.

Real files have these traits, and the builders copy them:
- one API response is written as several "assistant" lines (one per content block),
  all with the same requestId, message.id and usage block;
- tool results are stored as "user" lines with tool_result content;
- subagents write to <project>/<session>/subagents/agent-<id>.jsonl with isSidechain true
  and the parent's sessionId;
- system notes are "user" lines with isMeta true.
"""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SECRET_PROMPT = "SECRET-PROMPT-please-refactor-billing"
SECRET_CODE = "def secret_function_xyz(): return 42"
SECRET_CWD = "/Users/alice/secret-project"
SECRET_PROJECT_DIR = "-Users-alice-secret-project"

_counter = itertools.count(1)


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Session:
    def __init__(
        self,
        root: Path,
        session_id: str | None = None,
        project_dir: str = SECRET_PROJECT_DIR,
        cwd: str = SECRET_CWD,
        agent_id: str | None = None,
        parent: "Session | None" = None,
    ):
        self.root = root
        self.session_id = session_id or (parent.session_id if parent else str(uuid.uuid4()))
        self.project_dir = project_dir
        self.cwd = cwd
        self.agent_id = agent_id
        self.lines: list[dict] = []

    @property
    def path(self) -> Path:
        base = self.root / self.project_dir
        if self.agent_id:
            return base / self.session_id / "subagents" / f"agent-{self.agent_id}.jsonl"
        return base / f"{self.session_id}.jsonl"

    def _base(self, at: datetime, **extra) -> dict:
        rec = {
            "parentUuid": None,
            "isSidechain": bool(self.agent_id),
            "userType": "external",
            "cwd": self.cwd,
            "sessionId": self.session_id,
            "version": "2.1.314",
            "gitBranch": "main",
            "uuid": str(uuid.uuid4()),
            "timestamp": ts(at),
        }
        if self.agent_id:
            rec["agentId"] = self.agent_id
        rec.update(extra)
        return rec

    def user(self, at: datetime, text: str = SECRET_PROMPT, **extra) -> "Session":
        self.lines.append(self._base(at, type="user", message={"role": "user", "content": text}, **extra))
        return self

    def user_blocks(self, at: datetime, blocks: list[dict], **extra) -> "Session":
        self.lines.append(self._base(at, type="user", message={"role": "user", "content": blocks}, **extra))
        return self

    def meta(self, at: datetime, text: str = "<system-reminder>note</system-reminder>") -> "Session":
        return self.user(at, text, isMeta=True)

    def tool_result(self, at: datetime, output: str = SECRET_CODE) -> "Session":
        rec = self._base(
            at,
            type="user",
            message={
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": output}],
            },
            toolUseResult={"stdout": output},
        )
        self.lines.append(rec)
        return self

    def request(
        self,
        at: datetime,
        input: int = 5,
        output: int = 500,
        cache_write: int = 1_000,
        cache_read: int = 50_000,
        model: str = "claude-opus-5-5",
        effort: str | None = None,
        blocks: int = 3,
        request_id: str | None = None,
        partial_first: bool = False,
    ) -> "Session":
        n = next(_counter)
        rid = request_id or f"req_{n:06d}"
        mid = f"msg_{n:06d}"
        kinds = ["thinking", "text", "tool_use"]
        for i in range(blocks):
            out = 1 if (partial_first and i == 0) else output
            usage = {
                "input_tokens": input,
                "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cache_read,
                "output_tokens": out,
                "service_tier": "standard",
                "cache_creation": {"ephemeral_1h_input_tokens": cache_write, "ephemeral_5m_input_tokens": 0},
            }
            block = {"type": kinds[i % 3]}
            if block["type"] == "text":
                block["text"] = SECRET_CODE
            if block["type"] == "tool_use":
                block.update({"id": "toolu_1", "name": "Bash", "input": {"command": f"cat {self.cwd}/x.py"}})
            extra = {"requestId": rid, "requestedModel": model}
            if effort:
                extra["effort"] = effort
                extra["perTurnEffort"] = effort
            self.lines.append(
                self._base(
                    at + timedelta(milliseconds=200 * i),
                    type="assistant",
                    message={
                        "model": model,
                        "id": mid,
                        "type": "message",
                        "role": "assistant",
                        "content": [block],
                        "stop_reason": "tool_use",
                        "usage": usage,
                    },
                    **extra,
                )
            )
        return self

    def raw(self, line: str) -> "Session":
        self.lines.append({"__raw__": line})
        return self

    def write(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as fh:
            for rec in self.lines:
                fh.write(rec["__raw__"] if "__raw__" in rec else json.dumps(rec, separators=(",", ":")))
                fh.write("\n")
        return self.path


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
