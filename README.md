# Buckshot Roulette RL Hackathon: game API and evaluation engine

Participants submit a `bot.py` with a `Bot` class. The engine plays their bots against each other
in 2–4 player Buckshot Roulette matches, each bot in its own sandbox, and produces a leaderboard
plus per-model training logs.

## Layout

```
schemas.py             data classes: observations, actions, enums (given)
game_API.py            the game simulation (initGame, step_PLAY, step_PICK_UPGRADE, ...)
wire.py                observation/action <-> JSON, shared by engine and sandbox
sandbox/runner.py      runs inside the container: loads the Bot, answers JSON-line requests
Dockerfile             sandbox image (python:3.12-slim, non-root)
bots/random_bot/       baseline bot (also the opponent used by validation)
engine/
  limits.py            all time and size limits (one dataclass)
  bot_process.py       starts one sandboxed bot (docker or local), timeouts, line protocol
  run_match.py         plays one match, fault handling, writes the log
  scoring.py           placement points, leaderboard, optional OpenSkill rating
  tournament.py        scheduling (balanced groups, finalists), parallel run, resume
  validate.py          smoke-test one submission
  export_logs.py       split match logs into one training file per model
scripts/test_container_timeout.py   original docker timeout experiment
```

## Architecture

```
host (trusted)                         sandbox (untrusted, one per bot)
engine/run_match.py                    sandbox/runner.py  ->  submission/bot.py
  holds the real GameState   -- obs -->   Bot.play / Bot.pick_upgrade
  (shell order, RNG)         <- action --
```

- The real `GameState` (including the hidden shell order) stays on the host. A bot only receives its
  own per-player observation, so it cannot read hidden information.
- Each bot gets one long-lived container per match: `--network=none`, memory/CPU/pid limits,
  read-only root filesystem, 64 MB tmpfs, all capabilities dropped, submission mounted read-only
  at `/submission`.
- Bot output (`print`) is redirected to stderr, so it cannot corrupt the protocol.

## Game as implemented (`game_API.py`)

- 2–4 players, health 5, no starting items.
- Session `s` (0-based): `2 * (s+1) * alive_players` shells, between 25% and 80% live.
- Shooting yourself with a blank gives another turn. Only a live shot damages (1, +1 per hand saw used).
- After a session ends: upgrade stage; `min(3*(s+1)*alive, 16*alive)` upgrades are offered and players
  pick one at a time in turn order. Session 0 offers juice, coffee, magnifying glass; later sessions
  also pool floatie and hand saw.
- Last player alive wins. `GameState.elimination_order` records deaths and gives placements.
- Added to the API: `elimination_order`, `eliminate_player()` (disqualification),
  `play_observation` / `upgrade_observation` (public names), `step_PICK_UPGRADE` (alias of
  `step_PICK_UPGRADES`).

## Writing a bot (participant interface)

A submission is a directory containing:

| File | Required | Purpose |
|---|---|---|
| `bot.py` | yes | defines `class Bot` |
| `params.json` | no | JSON object passed to the bot's `init` |
| model files, other code | no | anything `bot.py` needs (imports resolve from the submission directory) |

```python
from schemas import *          # Action_PLAY, ActionType, UpgradeType, NextRound, ...

class Bot:
    def init(self, params=None):       # called once per match; params = params.json contents
        ...
    def play(self, obs):               # obs: Obs_PLAY  -> return Action_PLAY
        ...
    def pick_upgrade(self, obs):       # obs: Obs_PICK_UPGRADES -> return Action_PICK_UPGRADES
        ...
```

`init` may take no arguments. If `Bot()` itself requires an argument, it receives the params dict.

Actions:

- Shoot: `ActionType.SHOOT`, `target=<player index>` (yourself or a living opponent).
- Use an upgrade: `ActionType.USE_UPGRADE`, `useUpgrade=UpgradeType.X`; `target` required only for
  `POOL_FLOATIE` (a living player other than yourself without a pending skip).
- You may use any number of upgrades per turn before shooting. Each `play` call is one action.
- Upgrade pick: `Action_PICK_UPGRADES` with `chosen_upgrade` set to a type that is still available.

Observations (see `schemas.py`): `Obs_PLAY` has players' health/upgrades, `turn` (your own index),
shell counts, `ejections` (what *you* know about ejected shells; others' ejections are `unknowns`),
and `next_round` (`UNKNOWN` unless you just used the magnifying glass).

## Limits (`engine/limits.py`)

| Limit | Default | When exceeded |
|---|---|---|
| Per-move timeout | 0.05 s | timeout fault (strike); a safe default move is played |
| Init timeout | 2 s | bot is disqualified |
| Decision time per bot per match | 0.5 s | `budget` fault, bot is disqualified |
| Strikes | 2 | bot is disqualified |
| Actions per match | 300 | match ends; survivors ranked by health |
| Container memory | 128m | container is killed |
| Submission size | 5 MB | rejected by validation and by the tournament |
| Bot output line | 64 KB | treated as a crash |

Faults: `timeout`, `error` (bot raised), `invalid` (unparseable action), `illegal` (rejected by the
game), `crash`, `budget`. Crash and budget disqualify immediately. A disqualified bot is eliminated
from the game and places below everyone still alive.
Worst-case time of a 4-bot match: `4 * (init_timeout + bot_time_budget)` = 10 s.

Timeouts are wall-clock. Running too many parallel matches on a loaded host causes false timeouts
(measured: 20 ms with 16 workers on 12 cores gave faults in 8 of 240 matches; 50 ms was clean).
The default `--workers` is half the CPU count for this reason.

Memory 128m and size 5 MB are very small: numpy/torch may not fit. Tell participants.

## Commands

### Setup

```
docker build -t cses-arcade-sandbox .          # sandbox image; rebuild after changing schemas.py, wire.py or sandbox/
pip install openskill                           # optional: adds a `skill` rating column
```

`--backend local` runs bots as plain subprocesses with no isolation or limits except the timeouts.
Use it for development only; tournaments must use `--backend docker` (the default).

### Validate a submission

```
python -m engine.validate SUBMISSION_DIR [--backend docker|local] [--image NAME] [--games 3]
```

Plays `--games` matches with the submission in seat 0 against three baseline random bots, prints
placement / actions / time used per game, shows stderr and the first fault on failure, and exits 1
if there is any problem (missing `bot.py`, too large, any fault).

### Run a tournament (or a single eval)

```
python -m engine.tournament [SUBMISSION_DIR ...] [--root DIR] [options]
```

| Option | Default | Meaning |
|---|---|---|
| `--root DIR` | | add every subdirectory of DIR as a submission (invalid ones are reported and skipped) |
| `--seeds N` | 5 | seeds per group; every seating of the group is played on each seed |
| `--group-size K` | 4 | players per match (capped at the number of submissions) |
| `--max-groups G` | 50 | if C(n,K) > G, use G balanced groups; applies to both phases |
| `--finalists M` | 0 | phase 2: rank after phase 1, then play groups drawn from the top M |
| `--tournament-seed S` | 0 | seeds the group sampling and the match seeds |
| `--deadline SEC` | none | stop starting new matches after SEC seconds |
| `--out DIR` | `out` | output directory |
| `--backend` | `docker` | `docker` or `local` |
| `--image` | `cses-arcade-sandbox` | docker image |
| `--workers W` | cpu/2 | matches in parallel (each uses K bot processes) |
| `--move-timeout SEC` | 0.05 | override the per-move timeout |
| `--bot-time-budget SEC` | 0.5 | override the per-bot decision-time budget |

Examples:

```
# eval 2-4 models: k! * seeds matches
python -m engine.tournament subs/a subs/b subs/c subs/d --seeds 100

# full leaderboard run
python -m engine.tournament --root submissions/ --max-groups 200 --seeds 5 --finalists 12 --deadline 10800

# dev run without docker
python -m engine.tournament bots/random_bot subs/a --backend local --seeds 10
```

Behaviour:

- **Seeds and seating.** For each group and seed index one game seed is derived
  (`sha256(tournament_seed|phase|group|seed_idx)`), and the group plays all k! seatings on it, so
  seat order and shell luck cancel out. A match can be replayed exactly from its seed and seating.
- **Balanced groups.** If all C(n,K) groups fit under `--max-groups` they are all played; otherwise
  groups are filled greedily with the least-used bots, so everyone plays about equally often.
- **Order and deadline.** Matches run seed by seed across groups, so a run cut off by `--deadline`
  still has even coverage.
- **Resume.** Each finished match is appended to `results.jsonl`; rerunning the same command skips
  matches already present. Use the same options (seed, groups) when resuming.
- **Phase 2.** The top `--finalists` bots by phase-1 leaderboard get new groups (same `--seeds`).
  The final leaderboard counts all matches from both phases.

Match id format: `p1_g0-2-7-9_s3_p0279` = phase 1, group of submissions 0,2,7,9, seed index 3,
seating (seat 0 = submission 0, seat 1 = 2, seat 2 = 7, seat 3 = 9).

### Export training logs

```
python -m engine.export_logs out/        # writes out/training/<model>.jsonl
```

### Output files (`--out DIR`)

| File | Content |
|---|---|
| `results.jsonl` | one match summary per line |
| `logs/<match_id>.jsonl` | one line per decision, last line `{"summary": ...}` |
| `leaderboard.json`, `leaderboard.csv` | final ranking |
| `training/<model>.jsonl` | after `export_logs`: that model's decisions |

Match summary: `match_id, seed, seats (names), placements (1 = winner, by seat), winner (seat),
reason (last_alive | max_actions), actions, faults (per seat, by kind), disqualified, time_used
(seconds per seat), final_health`.

Decision log line: `step, seat, stage, obs, action` plus `fault` and `detail` if the move failed.
A bot that fails to start gets a line with `stage: "INIT"`.

Training line: the decision line plus `match_id, seed, placement, points`.

### Scoring

Points by placement for a k-player match: `(k-1) - 2*(place-1)`, so 3, 1, -1, -3 for 4 players.
Leaderboard columns: `rank, name, matches, avg_points, win_rate, avg_place, faults, disqualified`,
and `skill` (OpenSkill Plackett-Luce, `mu - 3*sigma`) if openskill is installed.
Ranking is by `avg_points`, then `avg_place`.

## How long will it take?

Measured: about 13 matches per second (local backend, 12 cores). Docker will be slower because of
container startup, which dominates the cost. The limits only bound the worst case.

Matches = groups * k! * seeds. For 50 bots, the full plan (all 230,300 groups, 100 seeds) is 552.7
million matches, which is not feasible (hundreds of days). Sample instead:

| Setup | Matches | Time at 13/s |
|---|---|---|
| 200 groups, 5 seeds | 24,000 | about 31 min |
| 500 groups, 10 seeds | 120,000 | about 2.6 h |
| 200 groups, 5 seeds, plus `--finalists 12` (capped at 200 groups) | 48,000 | about 1 h |

Reusing bot containers across matches would be the main speed-up (not built).

## Status and known gaps

Tested with the local backend: crash / slow / illegal-move / over-budget / oversize / missing-`bot.py`
submissions, determinism across worker counts (for seeded bots), balanced groups, finalists,
deadline, resume, log export.

Not done or not verified:

- **The Docker backend has never been run** (Docker was not installed in the development
  environment). Build the image and run `engine.validate` first.
- The OpenSkill path has not been run (package not installed).
- No automated unit tests; no participant-facing problem statement beyond this file.
- The sandbox image contains only the standard library: participants needing numpy/torch need an
  image change, and 128m / 5 MB will not fit large models.
- Phase 2 uses the same `--seeds` as phase 1 (no separate flag).
- `scripts/test_container_timeout.py` comes from the Docker branch and is not used by the engine.
