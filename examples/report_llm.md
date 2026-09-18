# Playtest report

- Episodes: 3  |  Steps: 900  |  Coverage: 100%  |  LLM calls: 20
- Findings: 3

| ep | steps | tiles visited | outcome | findings |
|---|---|---|---|---|
| 0 | 300 | 103 | budget | 4 |
| 1 | 300 | 103 | budget | 0 |
| 2 | 300 | 103 | budget | 0 |

## Findings

### [CRITICAL] Goal tile reached but game did not end
- kind: `unwinnable`
- where: episode 0, step 155, player at (17, 16)
- detail: Player at (17, 16) on goal tile; won=False
- hypothesis: Win-condition check is not triggered on tile entry (missing goal-tile collision/event handler)
- repro (155 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, down x2, right x5, use_potion, right x4, up, right, down, left, right, down, left, right, down, left, down x4, left, up x3, left, down x3, right x3, down, up, buy_potion x3, up x2, right, down x3, right, up x4, right x2, down, right, down, right, down, left x3, buy_potion x3, left, down x3, use_potion, down x6, left, down, up x3, left, down x3, left, right x3, down, up x2, right, down

### [HIGH] Door opened without consuming a key
- kind: `door_no_key`
- where: episode 0, step 63, player at (9, 3)
- detail: Door(s) ['9,3'] opened; keys 2 -> 2
- hypothesis: Door-open logic fails to decrement key count or checks wrong door state before consuming inventory
- repro (63 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, down x2, right

### [HIGH] Purchase succeeded with insufficient gold
- kind: `purchase_without_funds`
- where: episode 0, step 102, player at (16, 9)
- detail: buy_potion with gold=0 succeeded (gold now -5)
- hypothesis: buy_potion lacks a gold>=cost guard before executing the transaction
- repro (102 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, down x2, right x5, use_potion, right x4, up, right, down, left, right, down, left, right, down, left, down x4, left, up x3, left, down x3, right x3, down, up, buy_potion x3