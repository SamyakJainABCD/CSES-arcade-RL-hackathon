# Findings

Every number here comes from the command printed next to it, run on branch `rl-gym-eval-suite`
(Linux, 12 cores, Python 3.14, local backend). Docker was not available on the measuring host, so
nothing below was measured in the Docker sandbox. Rollout numbers are exact repeats: everything is
seeded.

## 1. Pool floatie target was not range-checked (fixed)

`game_API._use_upgrade` indexed `state.players[target]` before validating `target`:

- `target=99` raised `IndexError`. `engine/run_match.py` only turned `ValueError` into an `illegal`
  fault, so the exception escaped `run_match`. It then escaped the `ThreadPoolExecutor.map` loop
  in `engine/tournament.py`, and one bad bot ended the whole tournament.
- `target=-1` used Python's negative indexing and put a floatie on the last seat. If the shooter
  *is* the last seat, it floaties itself, because `-1 != player_index`.
- `target=True` was treated as player 1 when the API was called directly. The wire layer already
  rejected booleans as `invalid`.

Fix: reject bool, non-int and out-of-range targets with `ValueError`. As defence in depth,
`run_match` now records any other exception raised by a step call as an `illegal` fault with
detail `engine error: ...`.

```
# on a checkout of main, with redteam/bots/floatie_99 copied into bots/:
python -m engine.tournament bots/floatie_99 bots/random_bot --backend local --seeds 6 --group-size 2 --out out
  -> IndexError: list index out of range; 0 of 12 results written, no leaderboard

python -m unittest tests.test_engine_bugs    # the 6 tests in the fix commit: before the fix FAILED (failures=2, errors=3)
                                             # (IndexError and KeyError escaping run_match); after: OK
```

## 2. The turn could pass to a dead player (fixed)

If the shooter killed itself while every other living player had a floatie pending,
`_advance_turn` skipped and cleared all of them, then fell back to `from_turn`, which is the dead
shooter. `step_PLAY` does not check that the player on turn is alive, so the dead player kept
playing. Fix: keep the old behaviour when `from_turn` is alive; otherwise give the turn to the next
living player.

The verifier finds this on the original engine:

```
mkdir orig && git show main:game_API.py > orig/game_API.py
cd orig && PYTHONPATH=.. python -m rlgym.verify --seeds 200 --players 3 4 --mask-every 1000000
# 7 violations "turn N belongs to a dead player": 4 of 200 3-player games, 3 of 200 4-player games
```

With the fix: 0 violations (section 6). The regression test replays seed 30 (3 players, random
legal play), which reached a dead player's turn at step 113 before the fix
(`tests/test_engine_bugs.py::TurnAfterSuicideTest`).

## 3. A hand saw survived its user's elimination (fixed, found during this work)

`state.damage` is reset only by a shot. Suppose a bot saws and is then disqualified on the same
turn: a second strike, a crash, a timeout that ends its budget. `eliminate_player` passes the turn
on, but the next player's live shot still does the extra damage. `eliminate_player` now resets
`damage` when it removes the player on turn.

```
python -m unittest tests.test_engine_bugs.SawAfterDisqualificationTest   # before: AssertionError: 2 != 1; after: OK
```

## 4. The gun is loaded by coin flips, not a shuffle (documented, not changed)

`_setup_round` flips a fair coin for each position while both kinds remain, and fills the rest
once one kind runs out. So:

- the next shell is live with probability exactly 1/2 whenever both kinds are left, whatever the
  counts;
- the end of the gun is usually a long run of the majority kind.

```
python -m rlgym.verify --seeds 200
  live_heavy_guns: 6661 of 20000 sampled guns have >= 60% live shells (mean live fraction 0.699)
  live_heavy_first_shell_live_rate: 0.508          # a shuffle would give ~0.699
  last_shell_is_majority_kind_rate: 0.869
  states_with_both_kinds_left: 13152, next_shell_live_rate: 0.502
  brier_naive: 0.2889   brier_exact: 0.2500       # live-left/shells-left is worse than a constant 0.5
```

This matters for players. `greedy_bot` and `belief_bot` share one policy and differ only in the
estimator, naive (live-left / shells-left) versus exact (`rlgym/belief.py`):

```
python -m rlgym.rollout bots/belief_bot bots/greedy_bot --seeds 500 --out out/ro
  belief_bot win rate 0.717 [0.688, 0.744] over 1000 matches (both seatings)
python -m rlgym.analysis out/ro/trajectories.jsonl
  greedy_bot shot itself at a true 50/50 on 2464 of 10937 shots (22.5%); belief_bot 0 of 23206
```

`rlgym.belief.p_next_live` is exact for this generator. It is checked against brute-force
enumeration of every gun `_setup_round` can produce (`tests/test_belief.py`). When other players
have ejected shells this player did not see, it weights prefix compositions by the generator DP ×
hypergeometric. That is exact if the unseen positions are uniform in the prefix.

Suggested one-line fix, if a shuffle was intended: build
`contents = [True] * live_count + [False] * blank_count` and call `state.rng.shuffle(contents)`.
This is a rule decision for the organisers. It changes the game for every seed, so existing logs
would no longer replay.

## 5. A floatie can be spent on an upgrade pick (documented, not changed)

The README says a floatie skips the target's "next play stage turn". But the pick stage also
advances turns with `skip_floaties=True`. A floatie that is still pending when a round ends is
consumed when the target's upgrade pick comes up: that player loses a pick and keeps their next
play turn.

```
python -m rlgym.verify --seeds 200
  floatie_spent_in_pick_stage: 42   (600 random legal games)
```

If that is not intended, pass `skip_floaties=False` from `_start_upgrade_stage` and from the
mid-stage advance in `step_PICK_UPGRADES`. The README now notes the current behaviour.

## 6. Verifier on the fixed engine

```
python -m rlgym.verify --seeds 200            # 2, 3 and 4 players, 200 random legal games each
  games 600, steps 52595, mask checks 447721, violations 0, determinism pairs 150 -> OK
```

The mask checks are sound and complete. Every action the observation-only mask allows succeeds
on a deep copy of the engine state, and every action it forbids raises `ValueError`. No other
exception type ever escaped the engine. Reshuffling the unfired shells never changed an
observation, and `next_round` was only ever visible to the player who used the glass.

## 7. Red team: the engine contains every adversarial bot

```
python -m redteam.run      # each bot vs random_bot through engine.run_match (local backend), 6 seeds
```

| bot | attack | engine verdict | disqualified |
|---|---|---|---|
| floatie_99 | floatie on player 99 | 8 × `illegal` | 4/6 matches |
| floatie_neg1 | floatie on player -1 | 8 × `illegal` | 4/6 |
| floatie_true | floatie on `True` | 8 × `invalid` (wire rejects bool) | 4/6 |
| raiser | raises in `play` | 12 × `error` | 6/6 |
| sleeper | sleeps 200 ms per move | 12 × `timeout` | 6/6 |
| slow_init | 3 s `init` (limit 2 s) | 6 × `crash` | 6/6 |
| garbage_action | returns `action="NUKE"` | 12 × `error` | 6/6 |
| garbage_line | writes non-JSON onto the protocol fd | 12 × `invalid` | 6/6 |
| huge_line | writes a 1 MB unterminated line | 6 × `crash` | 6/6 |

Every match returned a summary, and the honest opponent never picked up a fault. The floatie bots
are disqualified in only 4 of 6 matches because in 2 matches the game ended before they ever
held a floatie.

### Reading the hidden state: why graders must run bots out of process

`redteam/bots/gc_peeker` walks `gc.get_objects()`, finds the live `GameState` and reads
`round_contents`. When it finds nothing, it plays belief_bot's policy.

```
python -m redteam.run
  in-process (rlgym.rollout) vs greedy_bot:  gc_peeker 0.950 [0.924, 0.967]  (400 matches)
                                             belief_bot 0.7125 [0.666, 0.755] (same seeds)
  through engine.run_match vs greedy_bot:    gc_peeker 0.625 [0.516, 0.723]  (80 matches)
                                             belief_bot 0.625 [0.516, 0.723]  (same seeds)
```

In-process, the peek adds about 24 percentage points of win rate. Through the engine it is worth nothing:
the game lives in another process, and the peeker plays the same games as belief_bot. Anything
that loads bots into the grader's interpreter (`rlgym.rollout`, `rlgym.env`, a training loop) is
for trusted code only.

### Stalling at the 300-action cap

The engine ranks survivors by health at 300 actions. `redteam/bots/staller` is belief_bot, except
that when it leads on health it burns its turn on juice and magnifying glasses. It was compared
against the plain belief_bot in the same seat on the same seeds:

```
python -m redteam.run
  2 players: 400 paired matches; cap reached 0 (control 0); placement changed in 41: 2 better, 39 worse
  4 players: 800 paired matches; cap reached 1 (control 1); placement changed in 66: 2 better, 64 worse; won at cap 1
```

Naive stalling does not pay. Every stall uses up an upgrade, games rarely come near the cap (1
in 800 four-player games, control included), and the bot cannot see the action count, so it
cannot time a stall. The cap is still a weak spot for a smarter staller that only plays safe in
late sessions. Mitigations, cheapest first:

- show the action count (or the actions left) in the observation, so the cap is a fair, known
  rule rather than a hidden one;
- count only shots toward the cap, so upgrade use cannot run out the clock;
- break ties at the cap on something other than raw health, for example placement so far plus
  shells fired, or call it a draw (equal points for the survivors);
- scale the cap with the number of players and sessions.

### Reward hacking: damage dealt is not the objective

`NaiveDamageReward` (+1 per point of damage dealt) looks like a sensible dense reward. It ranks
four-player policies differently from the leaderboard:

```
python -m redteam.run      # 4-player table, 50 seeds x 24 seatings = 2400 matches per bot
  bot            avg damage   avg points   win rate
  belief_bot        7.36        +0.611      0.333
  random_bot        6.36        +0.966      0.499
  damage_farmer     4.60        -0.854      0.057
  greedy_bot        4.47        -0.723      0.110
  rank by damage: belief_bot > random_bot > damage_farmer > greedy_bot
  rank by points: random_bot > belief_bot > greedy_bot > damage_farmer   (2 of 6 pairs inverted)
```

An agent trained on the proxy would prefer belief_bot's style to random_bot's, which places
worse. Damage dealt rewards fighting, while placement rewards outliving. An explicit attempt to
farm the proxy (`damage_farmer`: saw every shot, never self-shoot) did not even win on damage, so
the proxy is not just easy to fool: it is simply misaligned. Train on `PlacementReward`, or on
`PotentialShapedReward`, whose return equals the placement return exactly
(`tests/test_env.py::test_shaped_return_equals_placement_return`).

## 8. Baselines and the LLM player

```
python -m rlgym.rollout bots/belief_bot bots/greedy_bot --seeds 500   # belief_bot 0.717 [0.688, 0.744], 1000 matches
python -m rlgym.rollout bots/belief_bot bots/random_bot --seeds 500   # belief_bot 0.597 [0.566, 0.627], 1000 matches
python -m rlgym.rollout bots/greedy_bot bots/random_bot --seeds 500   # greedy_bot 0.364 [0.335, 0.394], 1000 matches
python -m rlgym.rollout bots/belief_bot bots/greedy_bot bots/random_bot bots/random_bot --seeds 100
  # 2400 matches: avg points belief_bot +0.433, random_bot +0.314 (each), greedy_bot -1.062
  # win rate random_bot 0.345 (each), belief_bot 0.241, greedy_bot 0.069; 14 matches reached the 300-action cap
python -m rlgym.analysis <trajectories of the two 2-player runs above>
  # blunders per 100 decisions: belief_bot 0.0, greedy_bot 0.0, random_bot 4.756
  # random_bot shoots an opponent on a certain blank in 684 of 10759 shots (6.4%)
```

No bot faulted or made a decision slower than 50 ms. The slowest decision was 9.0 ms, by
random_bot in the 4-player run.

```
python -m rlgym.llm_eval --provider mock --seeds 20
  # 40 matches vs greedy_bot: win 0.650 [0.495, 0.779], parse failures 0.0, illegal actions 0.0,
  # 1031 decisions, blunders 7.3 per 100 (opponent shot on a certain blank in 36 of 369 shots)
```

No `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` was set on the measuring host, so only the offline
mock provider was evaluated. The mock is a rule-based stand-in that exercises the full
prompt → text → JSON → action path. Its numbers measure the harness, not a language model.

## Not measured here

- `python -m engine.validate <bot> --backend docker`: Docker is not installed on the measuring
  host. All engine runs above used the local backend, which enforces the same timeouts and
  protocol limits but not memory, network or filesystem isolation.
- Real LLM providers (no API keys) and coding-agent task T3 (agent runs were stopped to save
  usage). See `benchmarks/coding_agent/RESULTS.md`.
