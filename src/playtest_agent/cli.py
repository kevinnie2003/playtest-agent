"""Command-line entry point.

    playtest run   [--socket HOST:PORT] [--bug NAME ...] [--llm] [--episodes N] [--max-steps N] [--out report.md]
    playtest eval  [--llm] [--json out.json]
    playtest serve [--port 7777] [--bug NAME ...]
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent.client import LocalClient, SocketClient
from .agent.explorer import Explorer
from .agent.llm import make_planner
from .eval.harness import evaluate, format_table, make_flags
from .game.dungeon import BugFlags
from .report import to_markdown


def _flags(names: list[str]) -> BugFlags:
    flags = BugFlags()
    for n in names:
        one = make_flags(n)
        for k in BugFlags.all_names():
            v = getattr(one, k)
            if v:
                setattr(flags, k, v)
    return flags


def cmd_run(a: argparse.Namespace) -> int:
    if a.socket:
        host, port = a.socket.rsplit(":", 1)
        client = SocketClient(host, int(port))
    else:
        client = LocalClient(seed=a.seed, bugs=_flags(a.bug))
    planner = make_planner(use_llm=True if a.llm else None)
    ex = Explorer(client, planner=planner, seed=a.seed)
    res = ex.run(episodes=a.episodes, max_steps=a.max_steps)
    md = to_markdown(res)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        with open(a.out.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as fh:
            json.dump(res.to_dict(), fh, indent=2)
        print(f"wrote {a.out}")
    else:
        print(md)
    return 1 if any(f.severity == "critical" for f in res.findings) else 0


def cmd_eval(a: argparse.Namespace) -> int:
    rep = evaluate(a.episodes, a.max_steps, a.seeds, a.llm)
    print(format_table(rep))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2)
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .game.server import GameServer
    from .game.dungeon import Dungeon

    srv = GameServer((a.host, a.port), Dungeon(seed=a.seed, bugs=_flags(a.bug)))
    print(f"dungeon listening on {a.host}:{a.port} bugs={a.bug}")
    srv.serve_forever()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="playtest", description="Autonomous playtesting agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="play the game and write a bug report")
    r.add_argument("--socket", help="HOST:PORT of a running game server (default: in-process game)")
    r.add_argument("--bug", action="append", default=[], choices=BugFlags.all_names(), help="inject a bug (in-process only)")
    r.add_argument("--llm", action="store_true", help="force LLM planner on (default: on iff ANTHROPIC_API_KEY set)")
    r.add_argument("--episodes", type=int, default=3)
    r.add_argument("--max-steps", type=int, default=300)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--out", help="write Markdown report here (+ .json alongside)")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="measure detection of seeded bugs")
    e.add_argument("--episodes", type=int, default=3)
    e.add_argument("--max-steps", type=int, default=250)
    e.add_argument("--seeds", type=int, nargs="*", default=[0, 1])
    e.add_argument("--llm", action="store_true")
    e.add_argument("--json")
    e.set_defaults(fn=cmd_eval)

    s = sub.add_parser("serve", help="run the game over TCP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7777)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--bug", action="append", default=[], choices=BugFlags.all_names())
    s.set_defaults(fn=cmd_serve)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
