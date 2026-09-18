"""The explorer: a hybrid scripted + LLM policy that drives the game client,
runs detectors on every transition, and collects findings.

Policy priority each step:

1. Survival (drink a potion when low).
2. Pending literal actions from an LLM plan.
3. Probes: cheap edge-case experiments triggered by preconditions
   (use a potion at full HP, buy with no gold, push on locked doors and
   void tiles, ...). These are what a human QA tester does instinctively.
4. Coverage: BFS to the nearest unvisited reachable tile.
5. Goal: path to the exit once the map is exhausted.
6. Ask the LLM planner (if any) for an experiment; otherwise random.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .client import GameClient, Observation
from .detectors import Detector, Finding, GameProfile, Transition, default_detectors
from .llm import NullPlanner, Plan

Pos = Tuple[int, int]
MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
WALKABLE = set(".KP$SG/E@")


@dataclass
class EpisodeStats:
    episode: int
    steps: int
    visited: int
    outcome: str  # won | died | crashed | budget
    findings: int


@dataclass
class RunResult:
    findings: List[Finding]
    episodes: List[EpisodeStats]
    total_steps: int
    llm_calls: int
    coverage: float  # visited walkable tiles / all walkable tiles seen

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "episodes": [e.__dict__ for e in self.episodes],
            "total_steps": self.total_steps,
            "llm_calls": self.llm_calls,
            "coverage": self.coverage,
        }


class Explorer:
    def __init__(self, client: GameClient, detectors: Optional[List[Detector]] = None,
                 planner=None, profile: Optional[GameProfile] = None, seed: int = 0,
                 llm_every: int = 60):
        self.client = client
        self.detectors = detectors or default_detectors()
        self.planner = planner or NullPlanner()
        self.profile = profile or GameProfile()
        self.rng = random.Random(seed)
        self.llm_every = llm_every
        self.findings: List[Finding] = []
        self._seen_keys: Set[str] = set()

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def parse_map(render: str) -> List[str]:
        return render.split("\n")

    @staticmethod
    def char(rows: List[str], p: Pos) -> str:
        x, y = p
        if 0 <= y < len(rows) and 0 <= x < len(rows[y]):
            return rows[y][x]
        return " "

    def bfs(self, rows: List[str], start: Pos, passable, goal_fn) -> Optional[List[str]]:
        """Return the action list to the first tile satisfying goal_fn, or None."""
        q = deque([start])
        prev: Dict[Pos, Tuple[Pos, str]] = {}
        seen = {start}
        while q:
            cur = q.popleft()
            if cur != start and goal_fn(cur):
                path = []
                while cur != start:
                    cur, a = prev[cur]
                    path.append(a)
                return path[::-1]
            for a, (dx, dy) in MOVES.items():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in seen or not passable(nxt):
                    continue
                seen.add(nxt)
                prev[nxt] = (cur, a)
                q.append(nxt)
        return None

    # ---------------------------------------------------------------- policy
    def choose(self, obs: Observation, ep: "_Episode") -> Tuple[str, str]:
        s, rows = obs.state, self.parse_map(obs.render)
        me = tuple(s["player"])
        ep.visited.add(me)

        # 1. survival (skipped in "reckless" episodes, which deliberately test death)
        if not ep.reckless and s["hp"] <= 4 and s["potions"] > 0 and s["hp"] < s["max_hp"]:
            return "use_potion", "survival"

        # 2. pending literal plan
        if ep.pending:
            return ep.pending.pop(0), "plan"

        # 3. probes
        if s["hp"] >= s["max_hp"] and s["potions"] > 0 and "potion_full_hp" not in ep.probed:
            ep.probed.add("potion_full_hp")
            return "use_potion", "probe:potion_full_hp"
        on_shop = s["items"].get(f"{me[0]},{me[1]}") == "S"
        if on_shop and s["gold"] < 5 and "buy_no_gold" not in ep.probed:
            ep.probed.add("buy_no_gold")
            return "buy_potion", "probe:buy_no_gold"
        if on_shop and s["gold"] >= 5:  # buy until broke, then the no-gold probe fires
            return "buy_potion", "probe:buy_with_gold"
        if ep.reckless:  # hunt enemies: does damage / death behave?
            path = self.bfs(rows, me, lambda p: self.char(rows, p) in WALKABLE and self.char(rows, p) != "D",
                            lambda p: self.char(rows, p) == "E")
            if path:
                return path[0], "probe:seek_enemy"
        for a, (dx, dy) in MOVES.items():
            n = (me[0] + dx, me[1] + dy)
            c = self.char(rows, n)
            tag = f"push:{n}"
            if tag in ep.probed:
                continue
            if c == " ":  # void beyond the map edge: always push
                ep.probed.add(tag)
                return a, "probe:push_void"
            if c == "D" and s["keys"] == 0:  # locked door without key
                ep.probed.add(tag)
                return a, "probe:door_no_key"
            if c == "#":
                on_border = n[0] == 0 or n[1] == 0 or n[0] == len(rows[0]) - 1 or n[1] == len(rows) - 1
                if on_border or self.rng.random() < 0.15:  # always push the map border, sample inner walls
                    ep.probed.add(tag)
                    return a, "probe:push_border" if on_border else "probe:push_wall"
        if "wait" not in ep.probed and s["turn"] > 5:
            ep.probed.add("wait")
            return "wait", "probe:wait"

        # 4. coverage / 5. goal
        def passable(p: Pos) -> bool:
            c = self.char(rows, p)
            if c == "D":
                return s["keys"] > 0
            return c in WALKABLE

        # hoarder persona: grab every reachable pickup before spending anything on doors
        if ep.hoard:
            no_door = lambda p: self.char(rows, p) in WALKABLE and self.char(rows, p) != "D"  # noqa: E731
            path = self.bfs(rows, me, no_door, lambda p: self.char(rows, p) in "KP$")
            if path:
                return path[0], "probe:hoard"

        path = self.bfs(rows, me, passable, lambda p: p not in ep.visited and self.char(rows, p) != "D")
        if path is None:
            path = self.bfs(rows, me, passable, lambda p: self.char(rows, p) == "G")
            reason = "goal"
        else:
            reason = "explore"
        if path:
            return path[0], reason

        # 6. stuck: ask the planner, else random
        if self.planner.enabled and ep.steps - ep.last_llm >= 10:
            ep.last_llm = ep.steps
            plan = self.planner.suggest(obs.render, s, self.findings, "no unvisited reachable tiles and goal unreachable")
            ep.plans.append(plan)
            if plan.actions:
                ep.pending = list(plan.actions)
                return ep.pending.pop(0), "llm"
            if plan.target:
                p2 = self.bfs(rows, me, passable, lambda p: p == tuple(plan.target))
                if p2:
                    ep.pending = p2[1:]
                    return p2[0], "llm-target"
        return self.rng.choice(list(MOVES)), "random"

    # ---------------------------------------------------------------- run
    def run(self, episodes: int = 3, max_steps: int = 300) -> RunResult:
        """Play `episodes` episodes, rotating personas, and return findings."""
        stats: List[EpisodeStats] = []
        total = 0
        all_walkable: Set[Pos] = set()
        all_visited: Set[Pos] = set()
        for e in range(episodes):
            # rotate personas: cautious explorer, reckless fighter, item hoarder
            ep = _Episode(e, reckless=(e % 3 == 1), hoard=(e % 3 == 2))
            for d in self.detectors:
                d.reset()
            obs = self.client.reset()
            rows = self.parse_map(obs.render)
            all_walkable |= {(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c in WALKABLE}
            outcome = "budget"
            while ep.steps < max_steps:
                # periodic LLM consult even when not stuck (exploratory hypotheses)
                if self.planner.enabled and ep.steps and ep.steps % self.llm_every == 0 and not ep.pending:
                    plan = self.planner.suggest(obs.render, obs.state, self.findings, "periodic check-in")
                    ep.plans.append(plan)
                    ep.pending = list(plan.actions)
                action, why = self.choose(obs, ep)
                before, before_render = obs.state, obs.render
                ep.repro.append(action)
                nxt = self.client.step(action)
                ep.steps += 1
                total += 1
                t = Transition(before, action, nxt, before_render, e, ep.steps, ep.repro)
                for d in self.detectors:
                    for f in d.check(t, self.profile):
                        if f.key() not in self._seen_keys:
                            self._seen_keys.add(f.key())
                            self.findings.append(f)
                ep.visited.add(tuple(nxt.state["player"]))
                if nxt.crashed:
                    outcome = "crashed"
                    break
                if nxt.state["won"]:
                    outcome = "won"
                    break
                if nxt.state["dead"]:
                    outcome = "died"
                    break
                obs = nxt
            all_visited |= ep.visited
            stats.append(EpisodeStats(e, ep.steps, len(ep.visited), outcome,
                                      sum(1 for f in self.findings if f.episode == e)))
        coverage = len(all_visited & all_walkable) / max(1, len(all_walkable))
        self.findings = self.planner.triage(self.findings)
        return RunResult(self.findings, stats, total, getattr(self.planner, "calls", 0), coverage)


@dataclass
class _Episode:
    index: int
    reckless: bool = False
    hoard: bool = False
    steps: int = 0
    visited: Set[Pos] = field(default_factory=set)
    probed: Set[str] = field(default_factory=set)
    pending: List[str] = field(default_factory=list)
    repro: List[str] = field(default_factory=list)
    plans: List[Plan] = field(default_factory=list)
    last_llm: int = -100
