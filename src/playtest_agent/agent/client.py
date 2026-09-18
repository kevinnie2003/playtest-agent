"""Game client abstraction: the agent only ever sees this interface.

Two implementations:

* :class:`LocalClient` wraps a :class:`Dungeon` in-process (fast; used by eval).
* :class:`SocketClient` talks to ``playtest_agent.game.server`` over TCP, the
  same way it would talk to a real engine build.
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import List, Optional, Protocol

from playtest_agent.game.dungeon import BugFlags, Dungeon, GameError


@dataclass
class Observation:
    state: dict
    render: str
    crashed: bool = False
    error: Optional[str] = None


class GameClient(Protocol):
    def reset(self) -> Observation: ...
    def step(self, action: str) -> Observation: ...
    def actions(self) -> List[str]: ...
    def bounds(self) -> tuple[int, int]: ...


class LocalClient:
    def __init__(self, seed: int = 0, bugs: Optional[BugFlags] = None):
        self.game = Dungeon(seed=seed, bugs=bugs)

    def reset(self) -> Observation:
        st = self.game.reset()
        return Observation(st.to_dict(), self.game.render())

    def step(self, action: str) -> Observation:
        try:
            st = self.game.step(action)
        except GameError as e:
            return Observation(self.game.state().to_dict(), self.game.render(), crashed=True, error=str(e))
        return Observation(st.to_dict(), self.game.render())

    def actions(self) -> List[str]:
        return self.game.legal_actions()

    def bounds(self) -> tuple[int, int]:
        return self.game.width, self.game.height


class SocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 7777):
        self.sock = socket.create_connection((host, port))
        self.f = self.sock.makefile("rw", encoding="utf-8")
        self._last_state: dict = {}
        self._last_render: str = ""

    def _call(self, **req) -> dict:
        self.f.write(json.dumps(req) + "\n")
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise ConnectionError("game server closed connection")
        return json.loads(line)

    def _obs(self, resp: dict) -> Observation:
        if not resp.get("ok"):
            return Observation(self._last_state, self._last_render, crashed=bool(resp.get("crash")), error=resp.get("error"))
        self._last_state = resp.get("state", self._last_state)
        self._last_render = resp.get("render", self._last_render)
        return Observation(self._last_state, self._last_render)

    def reset(self) -> Observation:
        return self._obs(self._call(cmd="reset"))

    def step(self, action: str) -> Observation:
        return self._obs(self._call(cmd="step", action=action))

    def actions(self) -> List[str]:
        return self._call(cmd="actions")["actions"]

    def bounds(self) -> tuple[int, int]:
        r = self._call(cmd="bounds")
        return r["width"], r["height"]

    def close(self) -> None:
        self.sock.close()
