"""MCP server exposing the playtest agent as tools, so it can be driven from
Claude Code / Claude Desktop / any MCP client.

    playtest-mcp            # stdio transport

Tools:
  run_playtest(bugs, episodes, max_steps, seed)  -> Markdown report
  evaluate_agent(episodes, max_steps, seeds)    -> detection table
  list_bug_flags()                              -> names + docs of injectable bugs
  play_step(action) / play_reset() / play_view() -> drive one game interactively
"""
from __future__ import annotations

import json
from typing import List, Optional

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

from .agent.client import LocalClient
from .agent.explorer import Explorer
from .agent.llm import make_planner
from .eval.harness import evaluate, format_table, make_flags
from .game.dungeon import BugFlags, Dungeon, GameError
from .report import to_markdown

server = _Server("playtest-agent", instructions="Autonomous game playtesting agent. Use run_playtest to hunt "
                 "for bugs in the bundled dungeon (optionally with seeded bugs), evaluate_agent to score it, "
                 "or play_* tools to drive the game by hand.")

_game: Optional[Dungeon] = None


def _flags(names: Optional[List[str]]) -> BugFlags:
    flags = BugFlags()
    for n in names or []:
        one = make_flags(n)
        for k in BugFlags.all_names():
            if getattr(one, k):
                setattr(flags, k, getattr(one, k))
    return flags


@server.tool()
def list_bug_flags() -> str:
    """List the bug flags that can be injected into the test game for evaluation."""
    import inspect

    src = inspect.getsource(BugFlags)
    return "Injectable bugs:\n" + "\n".join(f"- {n}" for n in BugFlags.all_names()) + "\n\n" + src


@server.tool()
def run_playtest(bugs: Optional[List[str]] = None, episodes: int = 3, max_steps: int = 300,
                 seed: int = 0, use_llm: bool = False) -> str:
    """Run the autonomous playtest agent and return a Markdown bug report.

    bugs: optional list of BugFlags names to inject (see list_bug_flags).
    use_llm: consult an Anthropic model when the scripted explorer is stuck (needs ANTHROPIC_API_KEY).
    """
    client = LocalClient(seed=seed, bugs=_flags(bugs))
    ex = Explorer(client, planner=make_planner(use_llm=use_llm), seed=seed)
    res = ex.run(episodes=episodes, max_steps=max_steps)
    return to_markdown(res, title=f"Playtest report (bugs={bugs or []}, seed={seed})")


@server.tool()
def evaluate_agent(episodes: int = 3, max_steps: int = 250, seeds: Optional[List[int]] = None) -> str:
    """Score the agent: for each seeded bug, did it find it? Also counts false positives on the clean game."""
    return format_table(evaluate(episodes, max_steps, seeds or [0, 1]))


@server.tool()
def play_reset(bugs: Optional[List[str]] = None, seed: int = 0) -> str:
    """Start a fresh interactive game and return the map + state."""
    global _game
    _game = Dungeon(seed=seed, bugs=_flags(bugs))
    return play_view()


@server.tool()
def play_step(action: str) -> str:
    """Take one action (up/down/left/right/use_potion/buy_potion/wait) in the interactive game."""
    if _game is None:
        return "No game running; call play_reset first."
    try:
        st = _game.step(action)
    except GameError as e:
        return f"GAME CRASHED: {e}"
    return _game.render() + "\n" + json.dumps(st.to_dict())


@server.tool()
def play_view() -> str:
    """Show the current map and state of the interactive game."""
    if _game is None:
        return "No game running; call play_reset first."
    return _game.render() + "\n" + json.dumps(_game.state().to_dict())


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
