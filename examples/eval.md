| seeded bug | detected | steps to detect | kinds found |
|---|---|---|---|
| door_ignores_key | yes | 64 | door_no_key |
| east_wall_missing | yes | 124 | clip_through_wall |
| potion_no_consume_check | yes | 1 | wasted_resource |
| shop_allows_negative_gold | yes | 112 | negative_gold, purchase_without_funds |
| player_invulnerable | yes | 283 | damage_no_effect |
| softlock_after_turns | yes | 46 | softlock |
| key_overflow_crash | yes | 320 | crash |
| goal_does_not_win | yes | 160 | unwinnable |
| (clean game) | false positives: 0 | - | - |

recall = 1.00   precision = 1.00   (seeds=[0, 1, 2], episodes=3, max_steps=250, llm=False)
