"""Write a synthetic ~/.claude/projects folder for demos and the install smoke test.

Usage: python scripts/make_demo_data.py OUT_DIR [--end 2026-10-30] [--seed 0]

The data is made up. It copies the layout of real Claude Code transcripts (one line per
content block, shared request ids, subagent files, tool results) but no real content.
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Writer:
    def __init__(self, root: Path, project: str, session_id: str, agent: str | None = None):
        self.project = project
        self.session_id = session_id
        self.agent = agent
        base = root / f"-demo-{project}"
        self.path = base / session_id / "subagents" / f"agent-{agent}.jsonl" if agent else base / f"{session_id}.jsonl"
        self.lines: list[dict] = []
        self.n = 0

    def _rec(self, at: datetime, **kw) -> dict:
        rec = {
            "isSidechain": bool(self.agent),
            "userType": "external",
            "cwd": f"/demo/{self.project}",
            "sessionId": self.session_id,
            "version": "2.1.314",
            "uuid": str(uuid.uuid4()),
            "timestamp": ts(at),
        }
        if self.agent:
            rec["agentId"] = self.agent
        rec.update(kw)
        return rec

    def user(self, at: datetime) -> None:
        self.lines.append(self._rec(at, type="user", message={"role": "user", "content": "demo prompt"}))

    def tool_result(self, at: datetime) -> None:
        self.lines.append(
            self._rec(
                at,
                type="user",
                message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]},
                toolUseResult={"stdout": "ok"},
            )
        )

    def request(self, at: datetime, context: int, write: int, out: int, effort: str, model: str) -> None:
        self.n += 1
        rid = f"req_demo_{uuid.uuid4().hex[:16]}"
        usage = {
            "input_tokens": 4,
            "cache_creation_input_tokens": write,
            "cache_read_input_tokens": max(context - write, 0),
            "output_tokens": out,
        }
        for i, kind in enumerate(("thinking", "text", "tool_use")):
            self.lines.append(
                self._rec(
                    at + timedelta(milliseconds=300 * i),
                    type="assistant",
                    requestId=rid,
                    effort=effort,
                    message={"id": f"msg_{rid}", "model": model, "role": "assistant", "type": "message",
                             "content": [{"type": kind}], "usage": usage},
                )
            )

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as fh:
            for rec in self.lines:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def make(root: Path, end: date, seed: int) -> None:
    rng = random.Random(seed)
    projects = ["api-server", "web-app", "data-pipeline", "docs-site", "infra"]
    start = end - timedelta(days=20)
    day = start
    while day <= end:
        for _ in range(rng.randint(1, 4)):
            project = rng.choice(projects)
            sid = str(uuid.UUID(int=rng.getrandbits(128)))
            w = Writer(root, project, sid)
            at = datetime.combine(day, time(rng.randint(8, 20), rng.randint(0, 59)), tzinfo=timezone.utc)
            heavy = rng.random() < 0.08
            effort = "xhigh" if rng.random() < 0.3 else "high"
            model = "claude-opus-5-5" if rng.random() < 0.7 else "claude-sonnet-5-5"
            context = rng.randint(20_000, 40_000)
            turns = rng.randint(3, 40 if heavy else 15)
            subs = []
            for t in range(turns):
                w.user(at)
                for _ in range(rng.randint(2, 12 if heavy else 6)):
                    context += rng.randint(1_000, 6_000)
                    if context > 190_000:  # auto-compact, like Claude Code does
                        context = rng.randint(25_000, 45_000)
                    w.request(at, context, rng.randint(500, 5_000), rng.randint(100, 2_500), effort, model)
                    w.tool_result(at + timedelta(seconds=5))
                    at += timedelta(seconds=rng.randint(10, 60))
                if rng.random() < (0.25 if heavy else 0.08):
                    agent = uuid.UUID(int=rng.getrandbits(128)).hex[:16]
                    sub = Writer(root, project, sid, agent=agent)
                    sub_ctx = 15_000
                    for _ in range(rng.randint(8, 30)):
                        sub_ctx += rng.randint(2_000, 8_000)
                        sub.request(at, sub_ctx, rng.randint(1_000, 8_000), rng.randint(200, 2_000), effort, model)
                        at += timedelta(seconds=rng.randint(5, 30))
                    subs.append(sub)
                if rng.random() < 0.06:
                    at += timedelta(minutes=rng.randint(70, 300))  # walk away, cache expires
                    w.user(at)
                    w.request(at, context, context, rng.randint(200, 1_500), effort, model)
                at += timedelta(minutes=rng.randint(1, 8))
            w.write()
            for sub in subs:
                sub.write()
        day += timedelta(days=1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out_dir", type=Path)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    make(args.out_dir, args.end, args.seed)
    print(f"Wrote demo transcripts to {args.out_dir}")


if __name__ == "__main__":
    main()
