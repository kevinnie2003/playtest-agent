# playtest-agent

[![ci](https://github.com/kevinnie2003/playtest-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinnie2003/playtest-agent/actions/workflows/ci.yml) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

An autonomous QA agent that **plays a game, hunts for bugs, and writes a reproducible bug report**.

It drives a game purely through an observation/action interface (in-process or over a TCP socket, the way a real engine build would be driven), runs a set of *generic* bug oracles on every state transition, and produces a Markdown report with severity, root-cause hints, and an exact action sequence that reproduces each finding from reset.

It ships with:

- a small deterministic dungeon game with **8 switchable, seeded bugs** (soft lock, wall clipping, economy exploit, invulnerability, crash, unwinnable level, ...)
- a **hybrid scripted + LLM explorer** with rotating "personas" (cautious explorer, reckless fighter, item hoarder)
- an **evaluation harness** that measures precision and recall of the agent against the seeded bugs
- an **MCP server** so the agent can be driven from Claude Code, Claude Desktop, or any MCP client
- a test suite and a CI workflow

## Results

Scripted-only (no LLM, no API key, fully deterministic), 3 episodes x 250 steps per seed:

| seeded bug | detected | steps to detect |
|---|---|---|
| door_ignores_key | yes | 64 |
| east_wall_missing | yes | 124 |
| potion_no_consume_check | yes | 1 |
| shop_allows_negative_gold | yes | 112 |
| player_invulnerable | yes | 283 |
| softlock_after_turns | yes | 46 |
| key_overflow_crash | yes | 320 |
| goal_does_not_win | yes | 160 |
| (clean game) | 0 false positives | - |

**recall = 1.00, precision = 1.00** on seeds 0-2 (and on held-out seeds 3-4). See [`examples/eval.md`](examples/eval.md) and a sample report in [`examples/report_seeded_bugs.md`](examples/report_seeded_bugs.md).

## Quick start

```bash
pip install -e ".[dev]"          # core has zero runtime deps
playtest run                     # play the clean game, print a report
playtest run --bug softlock_after_turns --bug shop_allows_negative_gold --out report.md
playtest eval                    # precision/recall table against all seeded bugs
pytest                           # 29 tests, ~6 s
```

Drive a game over a socket, the way you would drive a real build:

```bash
playtest serve --port 7777 --bug east_wall_missing     # terminal 1
playtest run --socket 127.0.0.1:7777                    # terminal 2
```

`playtest run` exits non-zero when a **critical** finding exists, so it can gate a CI pipeline.

### With an LLM

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
playtest run --llm
```

The model is consulted only when the scripted explorer is stuck or at a periodic check-in, and once more at the end to triage findings (rank severity, write a root-cause hypothesis, drop duplicates). Cost is bounded by `max_calls`, with one call always reserved for triage. Without a key everything degrades to the scripted policy, so evaluation stays free and reproducible.

Run with `claude-sonnet-5`, 20 calls per run: recall and precision stay at 1.00 (the scripted policy already finds everything in this game), and each finding gets a one-line root cause. From [`examples/report_llm.md`](examples/report_llm.md):

| finding | model's hypothesis |
|---|---|
| Goal tile reached but game did not end | Win-condition check is not triggered on tile entry (missing goal-tile collision/event handler) |
| Door opened without consuming a key | Door-open logic fails to decrement key count or checks wrong door state before consuming inventory |
| Purchase succeeded with insufficient gold | buy_potion lacks a gold>=cost guard before executing the transaction |

All three are correct: they name the exact line each seeded bug removes. The first live run also exposed a bug in the agent itself: exploration consumed the whole call budget and triage silently got nothing, so every hypothesis was empty. Now fixed and covered by a test.

### As an MCP server

```bash
pip install -e ".[mcp]"
playtest-mcp
```

Add to Claude Code (`.mcp.json`):

```json
{ "mcpServers": { "playtest": { "command": "playtest-mcp" } } }
```

Tools: `run_playtest`, `evaluate_agent`, `list_bug_flags`, `play_reset`, `play_step`, `play_view`.

## How it works

```
 game (Dungeon | TCP server)
        |  observation: ASCII map + JSON state
        v
 Explorer  ──── policy each step ────────────────────────────────
        |   1. survival (drink potion when low)          [off in reckless persona]
        |   2. pending actions from an LLM plan
        |   3. probes: use potion at full HP, buy with no gold, push every
        |      map-border tile and locked door, hunt enemies, hoard items
        |   4. coverage: BFS to nearest unvisited reachable tile
        |   5. goal: path to the exit once the map is exhausted
        |   6. ask LLM planner for an experiment, else random
        v
 Detectors (run on every (before, action, after) transition)
        |   crash · numeric invariants · clip-through-wall / teleport ·
        |   door-without-key · wasted consumable / purchase-without-funds ·
        |   damage-without-effect · goal-without-win · soft lock
        v
 Findings  ──>  (optional LLM triage)  ──>  Markdown + JSON report
```

**Detectors are generic.** They encode invariants like *positions stay in bounds*, *resources never go negative*, *consuming a thing changes something*, *the game responds to input*, *a damage message means HP went down*. None of them knows about the specific seeded bugs. `GameProfile` holds the few game-specific knobs (which messages mean damage or healing, which tile is the goal).

**Personas matter more than cleverness.** The first version had a single cautious policy and found 3 of 8 bugs. Adding a reckless persona (fights enemies, never heals) found invulnerability, and a hoarder persona (grabs every pickup before opening doors) found the key-overflow crash. That took recall from 0.38 to 1.0 with no LLM involved.

**Every finding carries a repro.** The action list from reset is stored with the finding, and `tests/test_agent.py::test_repro_replays_to_same_state` checks that replaying it lands in the reported state.

## Design notes and tradeoffs

- **Why a bundled toy game?** So the evaluation is honest: the bugs are known, seeded one at a time, and the clean game is a real false-positive check. Porting to another game means implementing `GameClient` (reset/step/actions/bounds) and adjusting `GameProfile`.
- **Why scripted first, LLM second?** Scripted coverage is free, fast, and deterministic. The LLM adds value exactly where scripting runs out: hypothesising unusual inputs and explaining findings. Keeping it optional keeps CI reproducible.
- **Same-turn confounds.** An early version of the damage detector flagged "drink potion, then get hit" as damage-without-effect. The fix was making the game report the whole turn's events and teaching the detector about heal messages. This is the general lesson: oracles must understand the game's event granularity.
- **Dedup is per kind, not per instance.** The first occurrence of each finding kind is kept. A production version would key on (kind, location) and cluster.

## Roadmap

- Screenshot-based observation (vision model) for engines without a state API
- Coverage-guided fuzzing of action sequences near a finding to minimise repros
- Per-location finding clustering and a diff mode ("new since last build")
- Unity/Godot adapter over the same line-JSON protocol

## Layout

```
src/playtest_agent/
  game/       dungeon.py (game + BugFlags), server.py (TCP)
  agent/      client.py, explorer.py, detectors.py, llm.py
  eval/       harness.py (precision/recall)
  report.py   Markdown rendering
  cli.py      `playtest run|eval|serve`
  mcp_server.py
tests/        game, detectors, agent, socket, eval
examples/     sample reports + eval output
```

MIT licensed.
