# Buckshot Roulette RL Hackathon: game API and evaluation engine

## Arcade RL Hackathon by CSES NITW

This repository is for the Arcade RL Hackathon organized by CSES, NIT Warangal (NITW). Use it to
build, train, and evaluate bots for the Buckshot Roulette game.

There are two ways to get training experience:

- Use `game_API.py` to generate your own games, self-play trajectories, or training data.
- Use tournament game logs for offline reinforcement learning, or strategy
  analysis.

Your final submission is a bot that follows the interface below.

## Get Started

A submission is a directory containing `bot.py`. It may also contain `params.json` and model files.

```text
my_bot/
  bot.py
  params.json       # optional JSON object passed to init
  model.bin         # optional model or other files
```

The bot must define a `Bot` class:

```python
from schemas import Action_PLAY, Action_PICK_UPGRADES, ActionType, UpgradeType

class Bot:
    def init(self, params=None):
        # Called once at the start of each match.
        pass

    def play(self, obs):
        # Called during the PLAY stage.
        action = Action_PLAY()
        action.action = ActionType.SHOOT
        action.useUpgrade = None
        action.target = obs.turn
        return action

    def pick_upgrade(self, obs):
        # Called during the upgrade selection stage.
        action = Action_PICK_UPGRADES()
        action.chosen_upgrade = UpgradeType.JUICE
        return action
```

`init` may take no arguments. If constructing `Bot` requires an argument, the engine passes it the
params dictionary.

## Train With the Simulator

`game_API.py` provides the game state and turn-by-turn simulation functions. Use it to create
rollouts, run self-play, test strategies, or generate data for your training pipeline.

- `initGame(seed, num_players=2)` creates a seeded game for 2–4 players.
- `play_observation(state)` and `upgrade_observation(state)` return the current player's observation.
- `step_PLAY(state, action)` applies a play action.
- `step_PICK_UPGRADE(state, action)` applies an upgrade selection.
- `eliminate_player(state, player_index)` removes a player from a game.

In a simulation loop, check `state.stage`, get the matching observation, choose an action, and pass
it to the corresponding step function. The game ends when `state.game_over` becomes true. Use
different seeds for varied games and fixed seeds to reproduce a game.

**Use observations as the model input, not hidden state.** `GameState` contains information that
players cannot see, including the shell order in `round_contents`. For realistic training and
evaluation, make decisions using only `play_observation` or `upgrade_observation`, just as a
submitted bot does.

## Train From Tournament Logs

Each match log contains one JSON object per decision, followed by a match summary. Decision records
include the observation seen by the acting bot and, when available, the action it returned. The
summary includes the seed, bots, placements, faults, and final health.

After a tournament, export completed matches into one JSONL file per model:

```bash
python -m engine.export_logs out/
```

The exported files are written to `out/training/`. Each row includes the decision record and match
metadata such as `match_id`, `seed`, `placement`, and `points`. Use them to imitate policies, compare
decisions across states, build offline datasets, or analyze strategies and failure cases.

The logged action is what that bot chose, not necessarily an expert or optimal action. Fault records
may not contain an action. Export skips initialization failures and incomplete matches.

## Actions and Observations

During the `PLAY` stage, return one of these actions:

- **Shoot:** set `action` to `ActionType.SHOOT` and `target` to a living player's index. You may
  target yourself.
- **Use an upgrade:** set `action` to `ActionType.USE_UPGRADE` and `useUpgrade` to an available
  upgrade. `POOL_FLOATIE` also requires a target: a different living player without a pending skip.

During the upgrade selection stage, choose an upgrade that is still available in
`obs.available_upgrades`. Upgrade types are `JUICE`, `COFFEE`, `MAG_GLASS`, `POOL_FLOATIE`, and
`HAND_SAW`; not every type is available in every session.

See `schemas.py` for all fields. Play observations include player health and upgrades, your player
index, session and shell counts, your ejection information, and any known next-shell information.
They do not reveal the hidden shell order or other players' private ejection information.

## Game Rules

Buckshot Roulette is a 2–4 player turn-based game. Everyone starts with 5 health and no upgrades. At the
start of each round, players see how many live and blank shells are in the gun, but not their order.
The gun is loaded by a fair coin flip per position while both kinds remain, not a uniform shuffle,
so the next shell is live with probability 1/2 whenever both kinds are left (see `FINDINGS.md`). Players take
turns shooting a living player or themselves. A live shell damages its target; shooting yourself with a blank
grants another turn. Play continues until the gun is empty or one player remains. After each round, players
take turns choosing from the available upgrades. Each player can hold at most 15 upgrades; any upgrade picked
after reaching this limit is discarded:


• Juice restores 1 health, up to 5.


• Coffee ejects the next shell and privately reveals whether it was live or blank.


• Magnifying Glass privately reveals whether the next shell is live or blank.


• From round two onward, Pool Floatie can make another player skip their next play stage turn.
  (As implemented, a pending floatie is also spent if that player's upgrade pick comes first; see
  `FINDINGS.md`.)


• From round two onward, Hand Saw increases the next live shot’s damage by 1 and can stack.


On a play turn, a bot may use upgrades before shooting; each use is a separate action. The last player alive
wins. If the action limit is reached, remaining players are ranked by health. The implemented
rules are defined in `game_API.py`.

## Test Your Bot

Run a few matches against baseline random bots using the local backend:

```bash
python -m engine.validate my_bot/ --backend local
```

The local backend is convenient for development but does not isolate your code. To test using the
Docker sandbox, build the image and run validation:

```bash
docker build -t cses-arcade-sandbox .
python -m engine.validate my_bot/ --backend docker
```

Validation reports crashes, invalid actions, illegal moves, and timeouts.

## Run a Tournament

Evaluate two or more submissions:

```bash
python -m engine.tournament my_bot/ bots/random_bot --backend local --seeds 10
```

Or evaluate submission directories under a root folder:

```bash
python -m engine.tournament --root submissions/ --max-groups 200 --seeds 5 --out out/
```

The default backend is Docker. Run `python -m engine.tournament --help` to see options for group
size, seeds, workers, finalists, deadlines, and time budgets. Tournament output includes match
summaries, decision logs, and a leaderboard. Use the same options when resuming a run so completed
matches can be recognized.

### Submission Limits (Enforced by evaluation engine)

Each bot runs in one long-lived container for the duration of a match. Docker disables networking,
limits memory, CPU, and process count, uses a read-only root filesystem with a 64 MB `/tmp`, drops
all Linux capabilities, and mounts the submission directory read-only at `/submission`. Bot
`print()` output is redirected to stderr, keeping it separate from the JSON-lines protocol.

Default limits are:

| Limit | Default |
|---|---:|
| Time per decision | 0.05 seconds |
| Total decision time per bot per match | 0.5 seconds |
| Initialization time | 2 seconds |
| Container memory | 128 MB |
| Submission directory size | 5 MB |
| Actions per match | 300 |

Faults are recorded as `timeout` (wall-clock deadline exceeded), `error` (the bot raised an
exception), `invalid` (the action could not be parsed), `illegal` (the game rejected the action, or the engine raised an unexpected error on it),
`crash` (the bot process failed), or `budget` (the bot used its total decision-time allowance).
`crash` and `budget` disqualify a bot immediately; other fault kinds count toward the default
two-strike disqualification limit. A disqualified bot is eliminated and placed below every bot
still alive.

The worst-case duration of a four-bot match is `4 * (init_timeout + bot_time_budget)`, or 10 seconds
with the defaults. Timeouts use wall-clock time, so excessive parallelism on a loaded host can cause
false timeout faults. In one measured run, 16 workers on 12 cores with a 20 ms decision timeout
caused faults in 8 of 240 matches; 50 ms was clean. By default, `--workers` is half the CPU count
(at least one) to reduce this risk.

The Docker image contains Python's standard library. The 128 MB memory and 5 MB submission-size
limits are very small, so packages such as NumPy or PyTorch may not fit. The local backend is for
development and does not provide Docker's isolation or resource limits.

### Output files (`--out DIR`)

| File | Content |
|---|---|
| `results.jsonl` | One match summary per line. |
| `logs/<match_id>.jsonl` | One line per decision, followed by a final `{"summary": ...}` line. |
| `leaderboard.json`, `leaderboard.csv` | Final rankings. |
| `training/<model>.jsonl` | The model's decision records, created by `python -m engine.export_logs DIR`. |

A match summary contains `match_id`, `seed`, `seats` (bot names), `placements` (placement by seat,
with 1 as the winner), `winner` (winning seat), `reason` (`last_alive` or `max_actions`), `actions`,
`faults` (counts per seat and fault kind), `disqualified`, `time_used` (seconds per seat), and
`final_health`. Each decision record contains `step`, `seat`, `stage`, `obs`, and `action`; failed
moves also include `fault` and `detail`. A bot that fails during startup gets a record with
`stage: "INIT"`.

Exported training records add `match_id`, `seed`, `placement`, and `points` to each decision record.
For a match with `k` players, points are `(k - 1) - 2 * (place - 1)` (3, 1, -1, -3 in a four-player
match). The leaderboard columns are `rank`, `name`, `matches`, `avg_points`, `win_rate`, `avg_place`,
`faults`, and `disqualified`; ranking is by `avg_points`, then `avg_place`.

## RL Gym & Evaluation Suite

Tooling around the engine for training, evaluating and stress-testing bots, models and coding
agents. It uses only the standard library (gymnasium is used if installed). Run everything from
the repository root. Measured results, with the command behind each number, are in
[FINDINGS.md](FINDINGS.md).

| What | Where | Run |
|---|---|---|
| RL environment | `rlgym/env.py` | `BuckshotEnv(["bots/greedy_bot"], num_players=2)` (example below) |
| Reward functions | `rlgym/rewards.py` | `PlacementReward`, `PotentialShapedReward`, `NaiveDamageReward` |
| Next-shell belief | `rlgym/belief.py` | `p_next_live(obs)` (exact), `p_next_live_naive(obs)` |
| Engine verifier | `rlgym/verify.py` | `python -m rlgym.verify --seeds 200` |
| Rollout evaluation | `rlgym/rollout.py` | `python -m rlgym.rollout bots/belief_bot bots/greedy_bot --seeds 200 --out out/rollout` |
| Trajectory analysis | `rlgym/analysis.py` | `python -m rlgym.analysis out/rollout/trajectories.jsonl` (or a tournament `out/`) |
| Red-team testing | `redteam/` | `python -m redteam.run` |
| LLM player evaluation | `agents/llm_bot/`, `rlgym/llm_eval.py` | `python -m rlgym.llm_eval --provider mock --seeds 20` |
| Coding-agent benchmark | `benchmarks/coding_agent/` | `prepare.py`, `grade.py`, `run_agents.py` (below) |
| Tests | `tests/` | `python -m unittest` |

### Environment

```python
from rlgym.env import BuckshotEnv
from rlgym.rewards import PotentialShapedReward

env = BuckshotEnv(["bots/greedy_bot", "bots/random_bot"], num_players=3, agent_seat=1,
                  reward=PotentialShapedReward())
obs, info = env.reset(seed=0)
done = False
while not done:
    legal = [i for i, ok in enumerate(info["action_mask"]) if ok]
    obs, reward, terminated, truncated, info = env.step(legal[0])
    done = terminated or truncated
print(info["placement"])
```

- **Observation:** a fixed-length (60) float vector built only from the agent's own observation,
  with seats rotated so the agent is always seat 0. It includes the exact and naive next-shell
  beliefs.
- **Actions:** one `Discrete(16)` space for both stages (`rlgym/actions.py`): shoot relative seat
  0-3, juice/coffee/glass/saw, floatie on relative seat 1-3, pick one of five upgrades.
  `info["action_mask"]` marks the legal ones. The mask is computed from the observation and
  checked against the engine by the verifier.
- **Faults:** handled as in `engine.run_match`. An illegal action is a strike and the engine's
  fallback move is played; two strikes eliminate the agent.
- **Rewards:** `PlacementReward` returns exactly the leaderboard points.
  `PotentialShapedReward` adds potential-based shaping on the health lead (Ng, Harada & Russell,
  1999), so the optimal policy is unchanged. `NaiveDamageReward` is a documented hackable proxy.
- **Opponents:** bot directories are loaded in-process by `rlgym/loader.py`, which keeps each bot's
  helper modules private.

### Evaluation CLIs

- `rlgym.verify` plays random legal games and checks, after every step:
  - engine invariants;
  - mask soundness and completeness on deep copies;
  - no information leaks (reshuffling the unfired shells must not change the observation);
  - determinism.
  It also reports how biased the naive belief is. Exit code 1 on any violation.
- `rlgym.rollout` plays every seating on every seed, with fault rules identical to
  `engine.run_match`; `tests/test_rollout.py` checks that outcomes match. Writes trajectory
  JSONL (observation, action, legal mask, beliefs, fault, time) and a summary with win rate,
  Wilson 95% interval, average points, faults, and decisions slower than 50 ms.
- `rlgym.analysis` counts blunders (self-shot on a known live, opponent shot on a certain blank,
  wasted glass or juice, shots against the exact belief) from rollout trajectories or engine
  tournament logs.
- `redteam.run` runs adversarial bots (bad floatie targets, exceptions, sleeps, slow init,
  garbage and oversized protocol output, a bot that reads the hidden game state through `gc`, a
  staller) through `engine.run_match` and checks that each is faulted or disqualified correctly.
  It also measures peeking in-process vs out-of-process, stalling at the action cap, and reward
  hacking.
- `rlgym.llm_eval` evaluates `agents/llm_bot` against a baseline. It reports win rate, parse
  failures, illegal actions, blunders and tokens, and logs every prompt.
  - Providers: `mock` (offline), `anthropic` (`ANTHROPIC_API_KEY`), `openai` (`OPENAI_API_KEY`).
  - The LLM bot needs the network and is far slower than 50 ms per decision, so it is evaluated
    in-process, not in the sandbox.

In-process tools (`rollout`, `env`, `llm_eval`) are for trusted code. A bot loaded into the same
interpreter can read the hidden `GameState`: `redteam/bots/gc_peeker` does. **Grade untrusted
submissions only through `engine.run_match`.**

### Coding-agent benchmark

```bash
python -m benchmarks.coding_agent.prepare --task T1 --workspace /tmp/ws_t1   # public files only
# ... an agent edits /tmp/ws_t1 ...
python -m benchmarks.coding_agent.grade --task T1 --workspace /tmp/ws_t1
python -m benchmarks.coding_agent.run_agents --root out/agent_runs           # Claude Code, 3 runs per task
```

- **T1:** exact next-shell probability. A plausible wrong answer is included, and the grader
  rejects it.
- **T2:** fix the pool floatie crash in the original engine without changing any legal game. The
  grader rejects a fix that only checks the upper bound.
- **T3:** write a bot that beats greedy_bot through the sandboxed engine on hidden seeds.

The grader rebuilds the pristine workspace, rejects edits to protected files (sha256), and runs
candidate code in a separate `python -I` process against its own engine copy. Hidden tests live
in `benchmarks/coding_agent/hidden/` and never enter the workspace. Agent results are in
`benchmarks/coding_agent/RESULTS.md`.

## Repository Guide

- `game_API.py`: game simulation and state transitions
- `schemas.py`: observations, actions, and enums
- `wire.py`: JSON conversion used by the engine and sandbox
- `sandbox/runner.py`: loads a submitted bot and handles requests
- `engine/validate.py`: submission smoke tests
- `engine/tournament.py`: tournament scheduling and execution
- `engine/run_match.py`: runs one match and writes its log
- `engine/export_logs.py`: exports per-model training data
- `bots/random_bot/`, `bots/greedy_bot/`, `bots/belief_bot/`: baseline bots
- `Dockerfile`: sandbox image configuration
- `rlgym/`: RL environment, rewards, belief, verifier, rollout, analysis and LLM evaluation
- `redteam/`: adversarial bots and the containment harness
- `agents/llm_bot/`: language-model player (in-process evaluation only)
- `benchmarks/coding_agent/`: coding-agent benchmark with hidden graders
- `tests/`: `python -m unittest`
- `FINDINGS.md`: engine bugs, generator analysis and red-team results, with measurements

## You can check out the game at [Buckshot Roulette by CSES NITW](https://github.com/csesnitw/buckshot-roulette) to play and maybe get a better idea about it!
