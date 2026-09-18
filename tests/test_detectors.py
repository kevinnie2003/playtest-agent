from playtest_agent.agent.client import Observation
from playtest_agent.agent.detectors import (DamageDetector, DoorDetector, GameProfile, GoalDetector,
                                            InvariantDetector, ResourceDetector, SoftlockDetector, Transition)


def _state(**kw):
    base = dict(player=[1, 1], hp=10, max_hp=10, gold=0, keys=0, potions=1, turn=1, won=False, dead=False,
                enemies=[], items={}, doors_open=[], last_message="")
    base.update(kw)
    return base


def _t(before, action, after, render="###\n#.#\n###"):
    return Transition(before, action, Observation(after, render), render, 0, 1, [action])


P = GameProfile()


def test_invariant_negative_gold():
    f = InvariantDetector().check(_t(_state(), "buy_potion", _state(gold=-5)), P)
    assert [x.kind for x in f] == ["negative_gold"]


def test_door_without_key():
    f = DoorDetector().check(_t(_state(keys=0), "right", _state(keys=0, doors_open=["9,3"])), P)
    assert f and f[0].kind == "door_no_key"
    assert not DoorDetector().check(_t(_state(keys=1), "right", _state(keys=0, doors_open=["9,3"])), P)


def test_wasted_potion():
    f = ResourceDetector().check(_t(_state(hp=10, potions=1), "use_potion", _state(hp=10, potions=0)), P)
    assert f and f[0].kind == "wasted_resource"


def test_damage_no_effect_and_heal_same_turn():
    d = DamageDetector()
    assert d.check(_t(_state(hp=5), "wait", _state(hp=5, last_message="An enemy hits you for 1.")), P)
    assert not d.check(_t(_state(hp=5), "wait", _state(hp=4, last_message="An enemy hits you for 1.")), P)
    # potion (+5) then hit (-1): hp 4 -> 8 is legal, 4 -> 10 is not
    ok = _state(hp=8, last_message="You drink a potion. An enemy hits you for 1.")
    bad = _state(hp=10, last_message="You drink a potion. An enemy hits you for 1.")
    assert not d.check(_t(_state(hp=4), "use_potion", ok), P)
    assert d.check(_t(_state(hp=4), "use_potion", bad), P)


def test_goal_not_won():
    before = _state(items={"5,5": "G"})
    after = _state(player=[5, 5], items={}, won=False)
    assert GoalDetector().check(_t(before, "right", after), P)


def test_softlock_fires_after_silent_window():
    d = SoftlockDetector()
    d.reset()
    s = _state(last_message="")
    out = []
    for _ in range(P.softlock_window):
        out += d.check(_t(s, "left", s), P)
    assert [x.kind for x in out] == ["softlock"]
    # does not re-fire
    assert not d.check(_t(s, "left", s), P)
