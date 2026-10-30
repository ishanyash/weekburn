# WeekBurn v0.1 launch notes

## What it does

WeekBurn is a small command line tool that reads the Claude Code transcripts already on your computer and shows which sessions used the most tokens, and which of the causes Anthropic named (heavy sessions, subagents, idle resumes, long context, xhigh effort) explain it. It also tests whether your tokens per message really changed between two weeks, with 95% intervals and a check that removes the heaviest sessions, and prints a counts-only Markdown report you can paste into a GitHub issue.

## Who it is for

- Claude Code users on Pro or Max plans who hit their weekly limit sooner than expected and want to know whether their own usage changed.
- People filing or commenting on "usage draining fast" GitHub issues who want to add numbers without sharing prompts or code.

## Install

```bash
pipx install weekburn
weekburn report --since 7d
weekburn compare --before 2026-10-10:2026-10-16 --after 2026-10-24:2026-10-30
```

## Demo results (real transcripts)

PENDING: not measured yet. This section will hold the exact output of `weekburn report --since 7d --markdown` and `weekburn compare --before 2026-10-10:2026-10-16 --after 2026-10-24:2026-10-30 --markdown` run on Ishan's own transcripts. Do not post numbers until this section is filled in.

## Screenshots to take

1. `weekburn report --since 7d` in a terminal at least 140 columns wide, so the Model and Share columns show. Crop to the header, the top 10 table and the cause table.
2. `weekburn compare --before 2026-10-10:2026-10-16 --after 2026-10-24:2026-10-30`, framed on the two metric tables and the Verdict box.
3. The `--markdown` output pasted into a GitHub issue preview (use the Preview tab, do not submit), to show it renders as tables and holds no prompts or paths.

Check every screenshot for project folder names before posting: the terminal view shows them, the Markdown view does not.

## Facts for posts (checked 30 Oct 2026)

- On 28 Oct 2026 (23:51 UTC) Boris Cherny of Anthropic's Claude Code team posted the results of their review of "usage draining fast" reports: no single root cause and no regression in Claude Code, but "a few smaller things" with fixes rolling out. Most affected users had one or two heavy sessions using xhigh effort, `/goal`, Workflows, Agent Teams or long SDK jobs; subagents inherit the parent's effort level by default. Summary published 29 Oct: https://sysnote.net/news/claude-code-usage-draining-fast-anthropic-found-no-regression-blames-heavy-sessi
- GitHub issue #105240 (opened 26 Oct 2026): 94% of a Max 5x weekly allowance used in under 48 hours; the reporter first noticed faster use around 17 Oct and says it got much worse from 24 Oct: https://github.com/anthropics/claude-code/issues/105240 . Similar reports: #103437 (opened 19 Oct, Max 5x) and #105621 (opened 28 Oct, Max).
- A developer writing on dev.to (23 Oct 2026) read 471 sessions from one week, about 6.15B tokens: cache reads were about 97% of tokens, subagents about 32% of tokens and 64% of cache writes. 72 main-session cache breaks came after more than an hour idle (57 of them were him coming back to a session); at API list prices they were about 12% of the week's cost, the largest row in his cache-break table: https://dev.to/danmercede/i-read-all-471-of-my-claude-code-sessions-where-6-billion-tokens-actually-went-1bde

## What WeekBurn does not claim

- Token counts are not plan usage. Anthropic does not publish how the plan meter weights input, output, cache write and cache read tokens, so WeekBurn cannot say what share of a weekly limit was used.
- "No clear change in your local usage" means your own token use per message did not clearly change. It does not prove the meter is right or wrong.

## Links

- PyPI: https://pypi.org/project/weekburn/
- GitHub: https://github.com/ishanyash/weekburn
- Author: https://ishanyash.com
