"""A small deterministic grid dungeon used as the system-under-test.

The game is intentionally simple so that the *agent* is the interesting part.
Every mechanic here exists to give the playtesting agent something to break:

* rooms connected by locked doors (keys must be found first)
* enemies that damage the player on contact
* potions, a gold economy, and a shop
* a goal tile that ends the level

Bugs can be injected via :class:`BugFlags` for evaluation. In normal play every
flag is ``False`` and the game is (believed to be) correct.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

Pos = Tuple[int, int]

WALL = "#"
FLOOR = "."
DOOR = "D"
KEY = "K"
POTION = "P"
GOLD = "$"
SHOP = "S"
GOAL = "G"
ENEMY = "E"
START = "@"
VOID = " "

ACTIONS = ["up", "down", "left", "right", "use_potion", "buy_potion", "wait"]

# fmt: off
LEVEL_1 = [
    "##########           ",
    "#@..$...K#           ",
    "#..##....#           ",
    "#..#K....D......     ",
    "#..##....#     .     ",
    "#.K.E....#     .     ",
    "#........#  ###.#####",
    "##########  #.......#",
    "            #.$.E.P.#",
    "            #...S...#",
    "            #.......#",
    "            ###D#####",
    "              #.#    ",
    "              #.#    ",
    "            ###.#### ",
    "            #......# ",
    "            #.E..G.# ",
    "            #......# ",
    "            ######## ",
]
# fmt: on


@dataclass
class BugFlags:
    """Deliberately injectable defects. All False == 'correct' game."""

    # Doors can be opened without a key (progression / economy bug).
    door_ignores_key: bool = False
    # Moving right through the map's east edge wraps you off the grid.
    east_wall_missing: bool = False
    # Potion use when HP is full still consumes the potion (waste bug).
    potion_no_consume_check: bool = False
    # Shop lets you buy with insufficient gold (negative gold).
    shop_allows_negative_gold: bool = False
    # Enemy contact never reduces HP below 1 (accidental invulnerability).
    player_invulnerable: bool = False
    # After ~40 turns, game silently stops accepting move input (soft lock).
    softlock_after_turns: Optional[int] = None
    # Picking up a key when you already have >=2 crashes.
    key_overflow_crash: bool = False
    # Goal tile does not end the game (unwinnable).
    goal_does_not_win: bool = False

    @classmethod
    def all_names(cls) -> List[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class GameState:
    player: Pos
    hp: int
    max_hp: int
    gold: int
    keys: int
    potions: int
    turn: int
    won: bool
    dead: bool
    enemies: List[Pos]
    items: Dict[str, str]  # "x,y" -> tile char
    doors_open: List[str]  # "x,y"
    last_message: str

    def to_dict(self) -> dict:
        return asdict(self)


class GameError(RuntimeError):
    """Raised when the game itself crashes (a real bug, not a rule violation)."""


class Dungeon:
    """Deterministic dungeon. Same seed + same action sequence == same outcome."""

    def __init__(self, level: List[str] = LEVEL_1, seed: int = 0, bugs: Optional[BugFlags] = None):
        self.level_src = level
        self.seed = seed
        self.bugs = bugs or BugFlags()
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self) -> GameState:
        self.rng = random.Random(self.seed)
        self.height = len(self.level_src)
        self.width = max(len(r) for r in self.level_src)
        self.grid: List[List[str]] = []
        self.items: Dict[Pos, str] = {}
        self.enemies: List[Pos] = []
        self.doors_open: set = set()
        self.player: Pos = (0, 0)
        for y, row in enumerate(self.level_src):
            line = []
            for x in range(self.width):
                ch = row[x] if x < len(row) else VOID
                if ch == START:
                    self.player = (x, y)
                    ch = FLOOR
                elif ch in (KEY, POTION, GOLD, SHOP, GOAL):
                    self.items[(x, y)] = ch
                    ch = FLOOR
                elif ch == ENEMY:
                    self.enemies.append((x, y))
                    ch = FLOOR
                line.append(ch)
            self.grid.append(line)
        self.hp = 10
        self.max_hp = 10
        self.gold = 0
        self.keys = 0
        self.potions = 1
        self.turn = 0
        self.won = False
        self.dead = False
        self.last_message = "You enter the dungeon."
        return self.state()

    # ------------------------------------------------------------------ query
    def tile(self, pos: Pos) -> str:
        x, y = pos
        if not (0 <= x < self.width and 0 <= y < self.height):
            return VOID
        return self.grid[y][x]

    def in_bounds(self, pos: Pos) -> bool:
        return self.tile(pos) != VOID

    def state(self) -> GameState:
        return GameState(
            player=self.player,
            hp=self.hp,
            max_hp=self.max_hp,
            gold=self.gold,
            keys=self.keys,
            potions=self.potions,
            turn=self.turn,
            won=self.won,
            dead=self.dead,
            enemies=list(self.enemies),
            items={f"{x},{y}": ch for (x, y), ch in self.items.items()},
            doors_open=[f"{x},{y}" for (x, y) in sorted(self.doors_open)],
            last_message=self.last_message,
        )

    def render(self, radius: Optional[int] = None) -> str:
        """ASCII view. With radius, only the window around the player."""
        px, py = self.player
        rows = []
        y0, y1 = (0, self.height) if radius is None else (py - radius, py + radius + 1)
        x0, x1 = (0, self.width) if radius is None else (px - radius, px + radius + 1)
        for y in range(y0, y1):
            line = []
            for x in range(x0, x1):
                p = (x, y)
                if p == self.player:
                    line.append(START)
                elif p in self.enemies:
                    line.append(ENEMY)
                elif p in self.items:
                    line.append(self.items[p])
                elif self.tile(p) == DOOR and p in self.doors_open:
                    line.append("/")
                else:
                    line.append(self.tile(p))
            rows.append("".join(line))
        return "\n".join(rows)

    def legal_actions(self) -> List[str]:
        return list(ACTIONS)

    # ------------------------------------------------------------------ step
    def step(self, action: str) -> GameState:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        if self.won or self.dead:
            self.last_message = "Game is over."
            return self.state()

        self.turn += 1
        self.last_message = ""

        if self.bugs.softlock_after_turns and self.turn > self.bugs.softlock_after_turns:
            # Bug: input silently ignored, nothing changes, no message.
            self.last_message = ""
            return self.state()

        if action in ("up", "down", "left", "right"):
            self._move(action)
        elif action == "use_potion":
            self._use_potion()
        elif action == "buy_potion":
            self._buy_potion()
        elif action == "wait":
            self.last_message = "You wait."

        if not (self.won or self.dead):
            self._enemies_act()
        return self.state()

    def _move(self, direction: str) -> None:
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
        nx, ny = self.player[0] + dx, self.player[1] + dy
        target = (nx, ny)
        t = self.tile(target)

        if self.bugs.east_wall_missing and direction == "right" and nx >= self.width - 1:
            # Bug: bounds check off by one on the east edge.
            self.player = target
            self.last_message = "You step east."
            return

        if t == VOID or t == WALL:
            self.last_message = "Blocked."
            return
        if t == DOOR and target not in self.doors_open:
            if self.keys > 0 or self.bugs.door_ignores_key:
                if not self.bugs.door_ignores_key:
                    self.keys -= 1
                self.doors_open.add(target)
                self.last_message = "You unlock the door."
            else:
                self.last_message = "The door is locked. You need a key."
                return
        if target in self.enemies:
            self._fight(target)
            return
        self.player = target
        self._pickup(target)

    def _pickup(self, pos: Pos) -> None:
        item = self.items.get(pos)
        if item is None:
            return
        if item == KEY:
            if self.bugs.key_overflow_crash and self.keys >= 2:
                raise GameError("IndexError: key inventory slot 3 out of range")
            self.keys += 1
            self.last_message = "You pick up a key."
            del self.items[pos]
        elif item == POTION:
            self.potions += 1
            self.last_message = "You pick up a potion."
            del self.items[pos]
        elif item == GOLD:
            self.gold += 5
            self.last_message = "You pick up 5 gold."
            del self.items[pos]
        elif item == SHOP:
            self.last_message = "A shopkeeper. Potions cost 5 gold (buy_potion)."
        elif item == GOAL:
            if self.bugs.goal_does_not_win:
                self.last_message = "You stand on the exit. Nothing happens."
            else:
                self.won = True
                self.last_message = "You escape the dungeon!"

    def _fight(self, epos: Pos) -> None:
        # Player attacks: enemies die in one hit but retaliate first.
        self._damage(3, "The enemy strikes you for 3.")
        if not self.dead:
            self.enemies.remove(epos)
            self.last_message += " You slay the enemy."

    def _damage(self, amount: int, msg: str) -> None:
        if self.bugs.player_invulnerable:
            self.hp = max(1, self.hp - amount)
        else:
            self.hp -= amount
        # Append rather than overwrite so a turn's full story is visible
        # ("You drink a potion. An enemy hits you for 1.").
        self.last_message = (self.last_message + " " + msg).strip()
        if self.hp <= 0:
            self.hp = 0
            self.dead = True
            self.last_message += " You die."

    def _use_potion(self) -> None:
        if self.potions <= 0:
            self.last_message = "No potions."
            return
        if self.hp >= self.max_hp and not self.bugs.potion_no_consume_check:
            self.last_message = "You are already at full health."
            return
        self.potions -= 1
        self.hp = min(self.max_hp, self.hp + 5)
        self.last_message = "You drink a potion."

    def _buy_potion(self) -> None:
        if self.items.get(self.player) != SHOP:
            self.last_message = "There is no shop here."
            return
        if self.gold < 5 and not self.bugs.shop_allows_negative_gold:
            self.last_message = "Not enough gold."
            return
        self.gold -= 5
        self.potions += 1
        self.last_message = "You buy a potion."

    def _enemies_act(self) -> None:
        # Enemies adjacent to the player attack; others shuffle randomly.
        px, py = self.player
        new_positions: List[Pos] = []
        for (ex, ey) in self.enemies:
            if abs(ex - px) + abs(ey - py) == 1:
                self._damage(1, "An enemy hits you for 1.")
                new_positions.append((ex, ey))
                continue
            dx, dy = self.rng.choice([(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)])
            cand = (ex + dx, ey + dy)
            if self.tile(cand) == FLOOR and cand != self.player and cand not in new_positions and cand not in self.items:
                new_positions.append(cand)
            else:
                new_positions.append((ex, ey))
        self.enemies = new_positions

    # ------------------------------------------------------------------ misc
    def snapshot(self) -> "Dungeon":
        return copy.deepcopy(self)
