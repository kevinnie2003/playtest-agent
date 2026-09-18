# Playtest report

- Episodes: 3  |  Steps: 724  |  Coverage: 100%  |  LLM calls: 0
- Findings: 4

| ep | steps | tiles visited | outcome | findings |
|---|---|---|---|---|
| 0 | 300 | 103 | budget | 4 |
| 1 | 124 | 82 | died | 0 |
| 2 | 300 | 103 | budget | 0 |

## Findings

### [CRITICAL] Goal tile reached but game did not end
- kind: `unwinnable`
- where: episode 0, step 162, player at (17, 16)
- detail: Player at (17, 16) on goal tile; won=False
- repro (162 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, right, down x2, right x2, up, down, right, up, down, right, up, down, right, use_potion, up, down, right x2, up, down, right, up, right, down, right, down, left, right, down x5, left, up x3, left, down, left, down x2, right x3, down, up, buy_potion, use_potion, buy_potion x2, up x2, right, down x3, right, up x3, right x2, down, right, down, right, down, right, left x4, down, left, down x2, right, down x4, use_potion, down x2, left, down, up x2, left, down x3, right x3, down, up x2, right, down

### [HIGH] Door opened without consuming a key
- kind: `door_no_key`
- where: episode 0, step 64, player at (9, 3)
- detail: Door(s) ['9,3'] opened; keys 2 -> 2
- repro (64 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, right, down x2, right

### [HIGH] Invariant violated: negative_gold
- kind: `negative_gold`
- where: episode 0, step 112, player at (16, 9)
- detail: After 'buy_potion': gold went negative: -5
- repro (112 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, right, down x2, right x2, up, down, right, up, down, right, up, down, right, use_potion, up, down, right x2, up, down, right, up, right, down, right, down, left, right, down x5, left, up x3, left, down, left, down x2, right x3, down, up, buy_potion, use_potion, buy_potion x2

### [HIGH] Purchase succeeded with insufficient gold
- kind: `purchase_without_funds`
- where: episode 0, step 112, player at (16, 9)
- detail: buy_potion with gold=0 succeeded (gold now -5)
- repro (112 actions from reset): use_potion, up, left, down, left, down, left, wait, down, left, down, left, down, left, right, up x6, right, up, right, up, right, up, down x5, left, up x2, left, down, right x3, up x6, right, up, down x5, right, up x6, right, down x2, right x2, up, down, right, up, down, right, up, down, right, use_potion, up, down, right x2, up, down, right, up, right, down, right, down, left, right, down x5, left, up x3, left, down, left, down x2, right x3, down, up, buy_potion, use_potion, buy_potion x2