"""Render a RunResult as a Markdown bug report (what a QA lead would read)."""
from __future__ import annotations

from .agent.explorer import RunResult

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _compress(actions: list[str]) -> str:
    """'right right right up' -> 'right x3, up'."""
    if not actions:
        return "(none)"
    out, cur, n = [], actions[0], 1
    for a in actions[1:]:
        if a == cur:
            n += 1
        else:
            out.append(f"{cur} x{n}" if n > 1 else cur)
            cur, n = a, 1
    out.append(f"{cur} x{n}" if n > 1 else cur)
    return ", ".join(out)


def to_markdown(result: RunResult, title: str = "Playtest report") -> str:
    lines = [f"# {title}", ""]
    lines.append(f"- Episodes: {len(result.episodes)}  |  Steps: {result.total_steps}  |  "
                 f"Coverage: {result.coverage:.0%}  |  LLM calls: {result.llm_calls}")
    lines.append(f"- Findings: {len(result.findings)}")
    lines.append("")
    lines.append("| ep | steps | tiles visited | outcome | findings |")
    lines.append("|---|---|---|---|---|")
    for e in result.episodes:
        lines.append(f"| {e.episode} | {e.steps} | {e.visited} | {e.outcome} | {e.findings} |")
    lines.append("")
    if not result.findings:
        lines.append("No defects detected.")
        return "\n".join(lines)
    lines.append("## Findings")
    for f in sorted(result.findings, key=lambda f: (SEV_ORDER.get(f.severity, 9), f.step)):
        lines += [
            "",
            f"### [{f.severity.upper()}] {f.title}",
            f"- kind: `{f.kind}`",
            f"- where: episode {f.episode}, step {f.step}, player at {tuple(f.state.get('player', ()))}",
            f"- detail: {f.detail}",
        ]
        if f.hypothesis:
            lines.append(f"- hypothesis: {f.hypothesis}")
        lines.append(f"- repro ({len(f.repro)} actions from reset): {_compress(f.repro)}")
    return "\n".join(lines)
