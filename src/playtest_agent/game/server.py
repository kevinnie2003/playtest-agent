"""Line-delimited JSON game server over TCP.

This is how a *real* engine build would be driven: the agent never imports the
game, it only talks to a socket. Protocol (one JSON object per line):

    -> {"cmd": "reset"}
    -> {"cmd": "step", "action": "up"}
    -> {"cmd": "state"}
    -> {"cmd": "render", "radius": 3}
    -> {"cmd": "actions"}
    <- {"ok": true, "state": {...}, "render": "..."}
    <- {"ok": false, "error": "GameError: ..."}
"""
from __future__ import annotations

import argparse
import json
import socketserver
import traceback

from .dungeon import BugFlags, Dungeon, GameError


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        game: Dungeon = self.server.game  # type: ignore[attr-defined]
        for raw in self.rfile:
            raw = raw.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw)
                resp = dispatch(game, req)
            except GameError as e:
                resp = {"ok": False, "error": f"GameError: {e}", "crash": True}
            except Exception as e:  # noqa: BLE001
                resp = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
            self.wfile.write((json.dumps(resp) + "\n").encode())
            self.wfile.flush()


def dispatch(game: Dungeon, req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "reset":
        st = game.reset()
        return {"ok": True, "state": st.to_dict(), "render": game.render()}
    if cmd == "step":
        st = game.step(req["action"])
        return {"ok": True, "state": st.to_dict(), "render": game.render()}
    if cmd == "state":
        return {"ok": True, "state": game.state().to_dict()}
    if cmd == "render":
        return {"ok": True, "render": game.render(req.get("radius"))}
    if cmd == "actions":
        return {"ok": True, "actions": game.legal_actions()}
    if cmd == "bounds":
        return {"ok": True, "width": game.width, "height": game.height}
    return {"ok": False, "error": f"unknown cmd {cmd!r}"}


class GameServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, game: Dungeon):
        super().__init__(addr, _Handler)
        self.game = game


def main() -> None:
    p = argparse.ArgumentParser(description="Run the dungeon over TCP")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7777)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bug", action="append", default=[], help="inject a BugFlags field, e.g. --bug door_ignores_key")
    args = p.parse_args()
    bugs = BugFlags()
    for b in args.bug:
        if b == "softlock_after_turns":
            bugs.softlock_after_turns = 40
        else:
            setattr(bugs, b, True)
    srv = GameServer((args.host, args.port), Dungeon(seed=args.seed, bugs=bugs))
    print(f"dungeon listening on {args.host}:{args.port} bugs={[b for b in args.bug]}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
