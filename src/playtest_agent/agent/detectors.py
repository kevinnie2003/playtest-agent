"""Bug oracles. Each detector watches (before, action, after) transitions and
emits :class:`Finding` objects when a game invariant is violated.

Detectors are written against *generic* invariants (positions stay in bounds,
resources never go negative, consuming a resource has an effect, the game
responds to input, reaching the goal ends the game) rather than against the
specific bugs in :class:`BugFlags`, so they transfer to other games with the
same observation shape.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .client import Observation

MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
IMPASSABLE = {"#", " "}


@dataclass
class Finding:
    kind: str
    severity: str  # critical | high | medium | low
    title: str
    detail: str
    episode: int
    step: int
    state: dict
    repro: List[str] = field(default_factory=list)
    hypothesis: str = ""  # filled by LLM triage, optional

    def key(self) -> str:
        return f"{self.kind}"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "episode": self.episode,
            "step": self.step,
            "repro_len": len(self.repro),
            "repro": self.repro,
            "hypothesis": self.hypothesis,
            "state": self.state,
        }


@dataclass
class GameProfile:
    """Game-specific knobs the generic detectors need."""

    damage_patterns: Tuple[str, ...] = (r"hits you", r"strikes you")
    heal_patterns: Tuple[str, ...] = (r"drink a potion",)
    goal_tile: str = "G"
    door_tile: str = "D"
    softlock_window: int = 6
    stuck_window: int = 40


@dataclass
class Transition:
    before: dict
    action: str
    after: Observation
    before_render: str
    episode: int
    step: int
    repro: List[str]


class Detector:
    name = "base"

    def reset(self) -> None:  # called at episode start
        pass

    def check(self, t: Transition, profile: GameProfile) -> List[Finding]:
        raise NotImplementedError


def _char_at(render: str, pos) -> str:
    x, y = pos
    rows = render.split("\n")
    if 0 <= y < len(rows) and 0 <= x < len(rows[y]):
        return rows[y][x]
    return " "


class CrashDetector(Detector):
    name = "crash"

    def check(self, t, profile):
        if t.after.crashed:
            return [Finding("crash", "critical", "Game crashed",
                            f"Action {t.action!r} raised: {t.after.error}", t.episode, t.step, t.before, list(t.repro))]
        return []


class InvariantDetector(Detector):
    """Numeric state invariants that should hold in any inventory/HP game."""
    name = "invariant"

    def check(self, t, profile):
        s = t.after.state
        out = []
        checks = [
            (s["gold"] < 0, "negative_gold", "high", f"gold went negative: {s['gold']}"),
            (s["potions"] < 0, "negative_potions", "high", f"potions went negative: {s['potions']}"),
            (s["keys"] < 0, "negative_keys", "high", f"keys went negative: {s['keys']}"),
            (s["hp"] > s["max_hp"], "hp_over_max", "medium", f"hp {s['hp']} exceeds max {s['max_hp']}"),
            (s["hp"] < 0, "negative_hp", "medium", f"hp negative: {s['hp']}"),
            (s["dead"] != (s["hp"] <= 0), "death_state_mismatch", "high", f"dead={s['dead']} but hp={s['hp']}"),
        ]
        for cond, kind, sev, msg in checks:
            if cond:
                out.append(Finding(kind, sev, f"Invariant violated: {kind}", f"After {t.action!r}: {msg}",
                                   t.episode, t.step, s, list(t.repro)))
        return out


class ClipDetector(Detector):
    """Player moved onto a tile that was rendered as wall/void before the move."""
    name = "clip"

    def check(self, t, profile):
        if t.action not in MOVES:
            return []
        b, a = tuple(t.before["player"]), tuple(t.after.state["player"])
        if a == b:
            return []
        dx, dy = MOVES[t.action]
        if a != (b[0] + dx, b[1] + dy):
            return [Finding("teleport", "high", "Player teleported",
                            f"{t.action!r} moved player from {b} to {a} (non-adjacent)", t.episode, t.step, t.after.state, list(t.repro))]
        prev_char = _char_at(t.before_render, a)
        if prev_char in IMPASSABLE:
            return [Finding("clip_through_wall", "high", "Player walked through an impassable tile",
                            f"{t.action!r} from {b} entered {a} which rendered as {prev_char!r}",
                            t.episode, t.step, t.after.state, list(t.repro))]
        return []


class DoorDetector(Detector):
    """Opening a door must consume a key."""
    name = "door"

    def check(self, t, profile):
        opened = set(t.after.state["doors_open"]) - set(t.before["doors_open"])
        if opened and t.after.state["keys"] >= t.before["keys"]:
            return [Finding("door_no_key", "high", "Door opened without consuming a key",
                            f"Door(s) {sorted(opened)} opened; keys {t.before['keys']} -> {t.after.state['keys']}",
                            t.episode, t.step, t.after.state, list(t.repro))]
        return []


class ResourceDetector(Detector):
    """Consuming a consumable must change something."""
    name = "resource"

    def check(self, t, profile):
        b, a = t.before, t.after.state
        if t.action == "use_potion" and a["potions"] < b["potions"] and a["hp"] == b["hp"]:
            return [Finding("wasted_resource", "medium", "Potion consumed with no effect",
                            f"use_potion at hp={b['hp']}/{b['max_hp']} removed a potion but hp unchanged",
                            t.episode, t.step, a, list(t.repro))]
        if t.action == "buy_potion" and a["potions"] > b["potions"] and b["gold"] < 5:
            return [Finding("purchase_without_funds", "high", "Purchase succeeded with insufficient gold",
                            f"buy_potion with gold={b['gold']} succeeded (gold now {a['gold']})",
                            t.episode, t.step, a, list(t.repro))]
        return []


class DamageDetector(Detector):
    """A damage event must reduce HP by the amount the game *says* it did.

    Healing in the same turn (potion) is accounted for via profile.heal_patterns
    so that "drink potion, then get hit" is not a false positive."""
    name = "damage"

    def check(self, t, profile):
        msg = t.after.state.get("last_message", "")
        if not any(re.search(p, msg) for p in profile.damage_patterns):
            return []
        b, a = t.before, t.after.state
        if a["dead"]:
            return []
        healed = any(re.search(p, msg) for p in profile.heal_patterns)
        claimed = sum(int(n) for n in re.findall(r"for (\d+)", msg))
        if healed:
            # Net = heal - damage; we only know the heal is capped at max_hp, so the
            # strongest safe check is: hp must not exceed (max_hp - claimed).
            if claimed and a["hp"] > a["max_hp"] - claimed:
                return [Finding("damage_no_effect", "high", "Damage event did not reduce HP",
                                f"Message {msg!r} but hp {b['hp']} -> {a['hp']} (>{a['max_hp']}-{claimed})",
                                t.episode, t.step, a, list(t.repro))]
            return []
        if a["hp"] >= b["hp"]:
            return [Finding("damage_no_effect", "high", "Damage event did not reduce HP",
                            f"Message {msg!r} but hp {b['hp']} -> {a['hp']}", t.episode, t.step, a, list(t.repro))]
        if claimed and b["hp"] - a["hp"] < claimed:
            return [Finding("damage_no_effect", "high", "HP dropped less than the damage the game reported",
                            f"Message {msg!r} claims {claimed} but hp {b['hp']} -> {a['hp']}", t.episode, t.step, a, list(t.repro))]
        return []


class GoalDetector(Detector):
    """Standing on the goal tile must end the game."""
    name = "goal"

    def check(self, t, profile):
        a = t.after.state
        px, py = a["player"]
        if t.before["items"].get(f"{px},{py}") == profile.goal_tile and not a["won"]:
            return [Finding("unwinnable", "critical", "Goal tile reached but game did not end",
                            f"Player at {tuple(a['player'])} on goal tile; won={a['won']}", t.episode, t.step, a, list(t.repro))]
        return []


def _core(s: dict) -> tuple:
    return (tuple(s["player"]), s["hp"], s["gold"], s["keys"], s["potions"], tuple(map(tuple, s["enemies"])),
            tuple(sorted(s["items"].items())), tuple(s["doors_open"]))


class SoftlockDetector(Detector):
    """Game stops responding: repeated inputs produce identical state and no feedback,
    or the player position hasn't changed across a long window of movement attempts."""
    name = "softlock"

    def reset(self):
        self.silent = 0
        self.moves_since_pos_change = 0
        self.fired = False

    def check(self, t, profile):
        if self.fired:
            return []
        a = t.after.state
        unchanged = _core(a) == _core(t.before)
        if unchanged and not a.get("last_message"):
            self.silent += 1
        else:
            self.silent = 0
        if t.action in MOVES:
            if tuple(a["player"]) == tuple(t.before["player"]):
                self.moves_since_pos_change += 1
            else:
                self.moves_since_pos_change = 0
        if self.silent >= profile.softlock_window:
            self.fired = True
            return [Finding("softlock", "critical", "Game stopped responding to input",
                            f"{self.silent} consecutive actions produced no state change and no feedback (turn {a['turn']})",
                            t.episode, t.step, a, list(t.repro))]
        if self.moves_since_pos_change >= profile.stuck_window:
            self.fired = True
            return [Finding("softlock", "critical", "Player appears stuck",
                            f"{self.moves_since_pos_change} movement attempts without position change at {tuple(a['player'])}",
                            t.episode, t.step, a, list(t.repro))]
        return []


ALL_DETECTORS = [CrashDetector, InvariantDetector, ClipDetector, DoorDetector, ResourceDetector,
                 DamageDetector, GoalDetector, SoftlockDetector]


def default_detectors() -> List[Detector]:
    return [d() for d in ALL_DETECTORS]
