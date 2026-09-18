"""Optional LLM layer (Anthropic). Everything degrades gracefully to a
scripted-only run when no API key is present, so evaluation is reproducible
and free.

Two uses:

* :meth:`LLMPlanner.suggest` — when the scripted explorer runs out of ideas
  (nothing left to explore, goal unreachable), ask the model for a hypothesis
  and a concrete target/action sequence to try.
* :meth:`LLMPlanner.triage` — after a run, ask the model to rank findings,
  write a one-line hypothesis for the root cause, and drop likely duplicates.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .detectors import Finding

DEFAULT_MODEL = os.environ.get("PLAYTEST_MODEL", "claude-sonnet-5")


@dataclass
class Plan:
    hypothesis: str = ""
    target: Optional[tuple] = None       # (x, y) to path towards
    actions: List[str] = field(default_factory=list)  # literal actions to run first
    source: str = "none"


class NullPlanner:
    """Scripted-only fallback. Never suggests anything."""
    enabled = False
    calls = 0

    def suggest(self, render: str, state: dict, findings: List[Finding], reason: str) -> Plan:
        return Plan(source="none")

    def triage(self, findings: List[Finding]) -> List[Finding]:
        return findings


SYSTEM = """You are an expert game QA engineer driving an automated playtest of a small
roguelike. You see an ASCII map and JSON state. Legend: # wall, . floor, D locked door,
/ open door, K key, P potion, $ gold, S shop, G goal/exit, E enemy, @ player.
Actions: up down left right use_potion buy_potion wait.
Your job is to find bugs: soft locks, clipping, economy exploits, invulnerability,
unwinnable states, crashes. Prefer unusual inputs and edge cases the scripted
explorer would not try. Respond with JSON only."""


class LLMPlanner:
    enabled = True

    def __init__(self, model: str = DEFAULT_MODEL, max_calls: int = 20):
        import anthropic  # local import so the package works without it

        self.client = anthropic.Anthropic()
        self.model = model
        self.max_calls = max_calls
        self.calls = 0

    def _ask(self, prompt: str, max_tokens: int = 600, reserved: bool = False) -> str:
        # One call is always held back for final triage so a long exploration
        # cannot starve the step that explains the findings.
        budget = self.max_calls if reserved else self.max_calls - 1
        if self.calls >= budget:
            return ""
        self.calls += 1
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    @staticmethod
    def _json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}

    def suggest(self, render: str, state: dict, findings: List[Finding], reason: str) -> Plan:
        slim = {k: v for k, v in state.items() if k not in ("items", "enemies")}
        prompt = (
            f"The scripted explorer is stuck. Reason: {reason}\n\n"
            f"MAP:\n{render}\n\nSTATE: {json.dumps(slim)}\n"
            f"FINDINGS SO FAR: {[f.kind for f in findings]}\n\n"
            "Propose ONE experiment. Reply as JSON: "
            '{"hypothesis": "...", "target": [x, y] or null, "actions": ["up", ...] (max 15)}'
        )
        data = self._json(self._ask(prompt))
        if not data:
            return Plan(source="llm-unparsed")
        tgt = data.get("target")
        acts = [a for a in data.get("actions", []) if isinstance(a, str)][:15]
        return Plan(hypothesis=str(data.get("hypothesis", "")), target=tuple(tgt) if tgt else None,
                    actions=acts, source="llm")

    def triage(self, findings: List[Finding]) -> List[Finding]:
        if not findings:
            return findings
        summary = [{"i": i, "kind": f.kind, "title": f.title, "detail": f.detail, "severity": f.severity}
                   for i, f in enumerate(findings)]
        prompt = (
            "Triage these automated playtest findings. For each index give a corrected severity "
            "(critical/high/medium/low), a one-sentence root-cause hypothesis, and whether it is a "
            "duplicate of an earlier index.\n"
            f"{json.dumps(summary, indent=1)}\n"
            'Reply as JSON: {"items": [{"i": 0, "severity": "high", "hypothesis": "...", "duplicate_of": null}]}'
        )
        data = self._json(self._ask(prompt, max_tokens=1500, reserved=True))
        keep: List[Finding] = []
        for item in data.get("items", []):
            i = item.get("i")
            if not isinstance(i, int) or not (0 <= i < len(findings)):
                continue
            if item.get("duplicate_of") is not None:
                continue
            f = findings[i]
            f.hypothesis = str(item.get("hypothesis", ""))
            if item.get("severity") in ("critical", "high", "medium", "low"):
                f.severity = item["severity"]
            keep.append(f)
        return keep or findings


def make_planner(use_llm: Optional[bool] = None, model: str = DEFAULT_MODEL):
    """Return an LLMPlanner if requested/possible, else NullPlanner."""
    want = os.environ.get("ANTHROPIC_API_KEY") is not None if use_llm is None else use_llm
    if not want:
        return NullPlanner()
    try:
        return LLMPlanner(model=model)
    except Exception:  # noqa: BLE001 - missing key, missing package, etc.
        return NullPlanner()
