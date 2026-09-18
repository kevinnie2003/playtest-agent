"""Evaluation harness: does the agent find the bugs we seeded?

For each bug flag we run the agent against a game with *only* that bug
enabled and check whether the expected finding kind appears. We also run the
clean game and count any finding as a false positive. Output is a table with
per-bug detection, steps-to-detect, and overall precision/recall.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from playtest_agent.agent.client import LocalClient
from playtest_agent.agent.explorer import Explorer
from playtest_agent.agent.llm import NullPlanner, make_planner
from playtest_agent.game.dungeon import BugFlags

# Which detector kind(s) count as "found it" for each seeded bug.
EXPECTED: Dict[str, List[str]] = {
    "door_ignores_key": ["door_no_key"],
    "east_wall_missing": ["clip_through_wall", "teleport"],
    "potion_no_consume_check": ["wasted_resource"],
    "shop_allows_negative_gold": ["purchase_without_funds", "negative_gold"],
    "player_invulnerable": ["damage_no_effect"],
    "softlock_after_turns": ["softlock"],
    "key_overflow_crash": ["crash"],
    "goal_does_not_win": ["unwinnable"],
}


@dataclass
class BugResult:
    bug: str
    detected: bool
    kinds_found: List[str]
    steps_to_detect: Optional[int]
    total_steps: int
    coverage: float
    seconds: float


def make_flags(bug: str) -> BugFlags:
    flags = BugFlags()
    if bug == "softlock_after_turns":
        flags.softlock_after_turns = 40
    else:
        setattr(flags, bug, True)
    return flags


def run_one(bug: Optional[str], episodes: int, max_steps: int, seeds: List[int], planner=None) -> BugResult:
    t0 = time.time()
    kinds: List[str] = []
    first: Optional[int] = None
    total = 0
    cov = 0.0
    for seed in seeds:
        client = LocalClient(seed=seed, bugs=make_flags(bug) if bug else BugFlags())
        ex = Explorer(client, planner=planner or NullPlanner(), seed=seed)
        res = ex.run(episodes=episodes, max_steps=max_steps)
        total += res.total_steps
        cov = max(cov, res.coverage)
        for f in res.findings:
            kinds.append(f.kind)
            if bug and f.kind in EXPECTED[bug]:
                so_far = sum(e.steps for e in res.episodes[: f.episode]) + f.step
                first = so_far if first is None else min(first, so_far)
    detected = bool(bug) and any(k in EXPECTED[bug] for k in kinds)
    return BugResult(bug or "(clean)", detected, sorted(set(kinds)), first, total, cov, round(time.time() - t0, 2))


def evaluate(episodes: int = 3, max_steps: int = 250, seeds: Optional[List[int]] = None, use_llm: bool = False) -> dict:
    seeds = seeds or [0, 1]
    planner = make_planner(use_llm=use_llm) if use_llm else NullPlanner()
    rows = [run_one(b, episodes, max_steps, seeds, planner) for b in EXPECTED]
    clean = run_one(None, episodes, max_steps, seeds, planner)
    tp = sum(1 for r in rows if r.detected)
    fn = len(rows) - tp
    fp = len(clean.kinds_found)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "bugs": [asdict(r) for r in rows],
        "clean": asdict(clean),
        "recall": recall,
        "precision": precision,
        "seeds": seeds,
        "episodes": episodes,
        "max_steps": max_steps,
        "llm": bool(use_llm and getattr(planner, "enabled", False)),
    }


def format_table(report: dict) -> str:
    lines = ["| seeded bug | detected | steps to detect | kinds found |", "|---|---|---|---|"]
    for r in report["bugs"]:
        mark = "yes" if r["detected"] else "**NO**"
        lines.append(f"| {r['bug']} | {mark} | {r['steps_to_detect'] if r['steps_to_detect'] is not None else '-'} | {', '.join(r['kinds_found']) or '-'} |")
    c = report["clean"]
    lines.append(f"| (clean game) | false positives: {len(c['kinds_found'])} | - | {', '.join(c['kinds_found']) or '-'} |")
    lines.append("")
    lines.append(f"recall = {report['recall']:.2f}   precision = {report['precision']:.2f}   "
                 f"(seeds={report['seeds']}, episodes={report['episodes']}, max_steps={report['max_steps']}, llm={report['llm']})")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate the playtest agent against seeded bugs")
    p.add_argument("--episodes", type=int, default=3)
    p.add_argument("--max-steps", type=int, default=250)
    p.add_argument("--seeds", type=int, nargs="*", default=[0, 1])
    p.add_argument("--llm", action="store_true", help="also use the LLM planner (needs ANTHROPIC_API_KEY)")
    p.add_argument("--json", help="write full report JSON here")
    args = p.parse_args()
    rep = evaluate(args.episodes, args.max_steps, args.seeds, args.llm)
    print(format_table(rep))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2)


if __name__ == "__main__":
    main()
