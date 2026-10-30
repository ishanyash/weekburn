# WeekBurn

**See which Claude Code sessions burned your weekly limit, and whether your usage per message really changed.**

![weekburn report on demo data](https://raw.githubusercontent.com/ishanyash/weekburn/main/docs/report.svg)

<sub>Screenshot made from synthetic demo data (`scripts/make_demo_data.py`), not a real account.</sub>

```bash
pipx install weekburn
weekburn report --since 7d
```

Live on PyPI: <https://pypi.org/project/weekburn/>

WeekBurn reads the transcripts Claude Code already keeps on your computer. It makes no network calls and uploads nothing.

## Why

In late October 2026 many people reported that their Claude Code weekly limit was draining much faster than before (for example [#105240](https://github.com/anthropics/claude-code/issues/105240)). Anthropic's Claude Code team said it found no single root cause and no regression in Claude Code, and pointed to one or two heavy sessions (xhigh effort, `/goal`, Workflows, Agent Teams, long SDK jobs) and to subagents that inherit the parent's effort level ([summary](https://sysnote.net/news/claude-code-usage-draining-fast-anthropic-found-no-regression-blames-heavy-sessi)).

That leaves one question for each user: is it me, or the meter? WeekBurn answers the part you can answer from local files, and gives you a short, counts-only report you can paste into a GitHub issue.

## Quick start

```bash
pipx install weekburn

# Your heaviest sessions in the last 7 days, with cause tags
weekburn report --since 7d

# Did tokens per message really change between two weeks?
weekburn compare --before 2026-10-10:2026-10-16 --after 2026-10-24:2026-10-30

# Same reports as Markdown, safe to paste into a GitHub issue
weekburn report --since 7d --markdown > report.md
weekburn compare --before 2026-10-10:2026-10-16 --after 2026-10-24:2026-10-30 --markdown > compare.md
```

`--since` takes `7d`, `48h`, `2w` or a date like `2026-10-20`. `--before` and `--after` take whole days in your computer's time zone, first and last day included. If your transcripts live somewhere else, add `--projects-dir PATH`.

## What you get

**`weekburn report`**

- Totals for the period: sessions, API requests, user messages and tokens, split into cache read, cache write, uncached input and output, plus the part that came from subagents.
- The top 10 sessions by tokens, each with its cause tags.
- A table of the share of all tokens that sits in sessions with each tag.

**`weekburn compare`**

![weekburn compare on demo data](https://raw.githubusercontent.com/ishanyash/weekburn/main/docs/compare.svg)

- Tokens per user message, cache read share and cache write share in each period.
- A 95% bootstrap interval for each number and for the change.
- The same comparison again with the top 5% heaviest sessions removed.
- A plain verdict: "your usage per message changed" or "no clear change in your local usage".

## Cause tags

A tag is only given when the data supports it. A session can have more than one.

| Tag | Rule |
| :--- | :--- |
| heavy session | In the top 5% of sessions by total tokens in the period (rounded up, so at least one) |
| subagent heavy | Over 50% of the session's tokens came from subagents |
| idle resume | A request after more than 60 minutes of silence that sent over 100k tokens not served from cache (the prompt cache had expired) |
| long context | The median prompt size of the main conversation is over 150k tokens |
| high effort | Over 50% of the session's tokens ran at `xhigh` or `max` effort. Only shown when your transcripts record effort |

## How it works

1. **Find files.** Every `*.jsonl` under `~/.claude/projects` and `~/.config/claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`), including subagent files in `<session>/subagents/`.
2. **One record per API request.** Claude Code writes each response as several lines, one per content block (thinking, text, each tool call), and every line repeats the same usage block. Adding up lines counts the same request 2 to 8 times. WeekBurn keeps one record per `requestId` (or `message.id` when there is no request id), also across files, so requests copied into a resumed session are not counted twice. If the copies differ, the largest count is kept.
3. **Per request** it keeps input, output, cache write and cache read tokens, the model, the session, whether it came from a subagent, the effort level when recorded, and the minutes since the previous request in the same session.
4. **Per session** it adds these up and gives the tags above.
5. **Compare.** For each period it sums tokens and user messages over sessions and divides (a ratio of sums, so long sessions count more than short ones). The interval comes from 2,000 bootstrap resamples of sessions, with a fixed seed so the same data gives the same answer. The change is called clear when its 95% interval does not include zero. Then everything is run again without the top 5% of sessions by tokens in each period.

### Transcript fields WeekBurn relies on

Checked against real transcripts written by Claude Code 2.1.314.

| Field | Where | Used for |
| :--- | :--- | :--- |
| `type` | every line | `assistant` lines carry usage; `user` lines are messages or tool results |
| `requestId`, then `message.id` | assistant lines | one record per API request |
| `message.usage.input_tokens` | assistant lines | uncached input |
| `message.usage.output_tokens` | assistant lines | output (includes thinking) |
| `message.usage.cache_creation_input_tokens` | assistant lines | cache write |
| `message.usage.cache_read_input_tokens` | assistant lines | cache read |
| `message.model` | assistant lines | model column |
| `timestamp` | every line | periods and idle gaps |
| `sessionId` | every line | grouping (subagent files carry the parent's id) |
| `isSidechain`, `agentId`, a `subagents/` folder | every line / path | subagent or main |
| `effort` (or `perTurnEffort`) | assistant lines | high effort tag (only recent Claude Code versions write it) |
| `isMeta`, `toolUseResult`, content block types | user lines | telling user messages apart from tool results and system notes |
| `cwd` | every line | project name in terminal output only, never in Markdown |

Seen but not used yet: `message.usage.cache_creation.ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens`, `service_tier`, `speed`, `output_tokens_details.thinking_tokens`, `entrypoint`.

**User messages** are `user` lines with text or an image that are not tool results, not system notes (`isMeta`), not subagent prompts, and not local command output or "[Request interrupted]" markers.

## Privacy

- Reads local files only. No network calls, no telemetry, nothing uploaded.
- `--markdown` output holds counts, dates, model names and the first 8 characters of random session ids. It never holds prompt text, file paths, project names or code. A test checks this.
- Terminal output shows the project folder name (the last part of the path) so you can find the session. Use `--markdown` when you share.

## Known limits

- **Token counts are not plan usage.** Anthropic does not publish how the plan meter weights input, output, cache write and cache read tokens, so WeekBurn cannot tell you what share of your weekly limit a session used. It can only tell you whether your local token use changed.
- **Old transcripts may be gone.** Claude Code deletes transcripts older than its `cleanupPeriodDays` setting (30 days by default), so `compare` can only look back as far as your files go.
- **"Heavy session" is relative.** It is the top 5% of the period, so there is always at least one.
- **Tags overlap,** so the cause shares do not add up to 100%.
- **Sessions are treated as independent** in the bootstrap. A session that spans both periods is split by request time and counts in both.
- **Slash commands** such as `/clear` are written as user lines and are counted as user messages. This is the same in both periods, so it does not bias the comparison much.
- **Few sessions, wide intervals.** With fewer than 5 sessions in a period WeekBurn warns you, and the intervals may be missing.
- **The transcript format is not a public API.** A future Claude Code version could change it.

## Development

```bash
git clone https://github.com/ishanyash/weekburn
cd weekburn
python -m pip install -e ".[test]"
python -m pytest
python scripts/make_demo_data.py /tmp/demo-projects   # synthetic data to try it on
weekburn report --since 7d --projects-dir /tmp/demo-projects
```

Releases are published to PyPI from GitHub Actions with trusted publishing when a `v*` tag is pushed. No API tokens are stored.

## Licence

MIT. See [LICENSE](LICENSE).

---

Built by [Ishan Yash](https://ishanyash.com).
