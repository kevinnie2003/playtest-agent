from playtest_agent.game.dungeon import BugFlags, Dungeon, GameError, LEVEL_1


def test_deterministic():
    a, b = Dungeon(seed=3), Dungeon(seed=3)
    acts = ["right", "right", "down", "down", "left", "wait", "up"] * 5
    for x in acts:
        sa, sb = a.step(x), b.step(x)
        assert sa == sb


def test_walls_block():
    g = Dungeon()
    p = g.player
    g.step("up")
    assert g.player == p and "Blocked" in g.last_message


def test_door_needs_key():
    g = Dungeon()
    g.player = (8, 3)
    g.step("right")
    assert g.player == (8, 3) and "locked" in g.last_message
    g.keys = 1
    g.step("right")
    assert g.player == (9, 3) and g.keys == 0 and "9,3" in g.state().doors_open


def test_door_bug_ignores_key():
    g = Dungeon(bugs=BugFlags(door_ignores_key=True))
    g.player = (8, 3)
    g.step("right")
    assert g.player == (9, 3) and g.keys == 0


def test_potion_full_hp_not_consumed():
    g = Dungeon()
    g.step("use_potion")
    assert g.potions == 1
    g2 = Dungeon(bugs=BugFlags(potion_no_consume_check=True))
    g2.step("use_potion")
    assert g2.potions == 0


def test_shop():
    g = Dungeon()
    g.player = (16, 9)  # shop tile
    g.step("buy_potion")
    assert g.potions == 1 and "Not enough" in g.last_message
    g.gold = 5
    g.step("buy_potion")
    assert g.potions == 2 and g.gold == 0
    gb = Dungeon(bugs=BugFlags(shop_allows_negative_gold=True))
    gb.player = (16, 9)
    gb.step("buy_potion")
    assert gb.gold == -5


def test_goal_wins():
    g = Dungeon()
    g.player = (16, 16)
    g.step("right")
    assert g.won
    gb = Dungeon(bugs=BugFlags(goal_does_not_win=True))
    gb.player = (16, 16)
    gb.step("right")
    assert not gb.won


def test_key_overflow_crash():
    g = Dungeon(bugs=BugFlags(key_overflow_crash=True))
    g.keys = 2
    g.player = (7, 1)
    try:
        g.step("right")  # key at (8,1)
    except GameError:
        return
    raise AssertionError("expected crash")


def test_level_is_solvable():
    # sanity: keys reachable before doors in LEVEL_1
    src = "\n".join(LEVEL_1)
    assert src.count("K") >= src.count("D")
