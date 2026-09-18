import socket
import threading

import pytest

from playtest_agent.agent.client import LocalClient, SocketClient
from playtest_agent.agent.explorer import Explorer
from playtest_agent.eval.harness import EXPECTED, evaluate, make_flags
from playtest_agent.game.dungeon import BugFlags, Dungeon
from playtest_agent.game.server import GameServer
from playtest_agent.report import to_markdown


def test_clean_game_has_no_findings():
    res = Explorer(LocalClient(seed=0), seed=0).run(episodes=3, max_steps=250)
    assert res.findings == []
    assert res.coverage > 0.6


@pytest.mark.parametrize("bug", list(EXPECTED))
def test_each_seeded_bug_is_found(bug):
    found = set()
    for seed in (0, 1):
        res = Explorer(LocalClient(seed=seed, bugs=make_flags(bug)), seed=seed).run(episodes=3, max_steps=250)
        found |= {f.kind for f in res.findings}
    assert found & set(EXPECTED[bug]), f"{bug}: found {found}"


def test_repro_replays_to_same_state():
    res = Explorer(LocalClient(seed=1, bugs=BugFlags(door_ignores_key=True)), seed=1).run(episodes=3, max_steps=250)
    f = next(x for x in res.findings if x.kind == "door_no_key")
    g = Dungeon(seed=1, bugs=BugFlags(door_ignores_key=True))
    for a in f.repro:
        g.step(a)
    assert list(g.player) == list(f.state["player"])
    assert g.state().doors_open == f.state["doors_open"]


def test_evaluate_reports_perfect_on_bundled_game():
    rep = evaluate(episodes=3, max_steps=250, seeds=[0, 1])
    assert rep["recall"] == 1.0 and rep["precision"] == 1.0


def test_markdown_report():
    res = Explorer(LocalClient(seed=0, bugs=BugFlags(goal_does_not_win=True)), seed=0).run(episodes=3, max_steps=250)
    md = to_markdown(res)
    assert "unwinnable" in md and "repro" in md


def test_socket_client_roundtrip():
    srv = GameServer(("127.0.0.1", 0), Dungeon(seed=0, bugs=BugFlags(east_wall_missing=True)))
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        c = SocketClient("127.0.0.1", port)
        obs = c.reset()
        assert obs.state["player"] == [1, 1]
        res = Explorer(c, seed=0).run(episodes=2, max_steps=200)
        assert any(f.kind == "clip_through_wall" for f in res.findings)
        c.close()
    finally:
        srv.shutdown()


def test_llm_planner_reserves_a_call_for_triage(monkeypatch):
    """Exploration may use at most max_calls-1; triage always gets the last one."""
    import sys
    import types

    from playtest_agent.agent import llm as L

    calls = []

    class _Resp:
        content = [types.SimpleNamespace(type="text", text='{"items": [{"i": 0, "severity": "low", "hypothesis": "h", "duplicate_of": null}]}')]

    class _Msgs:
        def create(self, **kw):
            calls.append(kw)
            return _Resp()

    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(messages=_Msgs()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    pl = L.LLMPlanner(max_calls=3)
    for _ in range(5):
        pl.suggest("", {}, [], "x")
    assert len(calls) == 2  # exploration capped at max_calls-1
    from playtest_agent.agent.detectors import Finding
    out = pl.triage([Finding("k", "high", "t", "d", 0, 1, {})])
    assert len(calls) == 3 and out[0].hypothesis == "h" and out[0].severity == "low"
