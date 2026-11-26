"""Verifier: play random legal games and check the engine after every step.

    python -m rlgym.verify [--seeds 200] [--players 2 3 4] [--mask-every 1] [--json report.json]

Checks
  invariants    shell conservation, health bounds, inventory <= 15, alive count, elimination
                order, turn on a living player, game_over iff <= 1 alive, damage >= 1
  mask          every action the mask allows succeeds on a deep copy (sound) and every action
                it forbids raises ValueError (complete); any other exception is an engine bug
  no-leak       the observation is unchanged when the unfired tail of the gun is reshuffled, it
                carries only the schema's fields, and next_round is revealed only to the player
                who used the magnifying glass since the last shell left the gun
  determinism   the same seed and actions give the same trajectory hash
  generator     how far live-left/shells-left is from the real next-shell frequency
Exit code 1 if any check fails.
"""
import argparse
import copy
import hashlib
import json
import random
import sys
from collections import Counter
from typing import Any, Dict, List

import game_API as api
import wire
from schemas import *

from .actions import N_ACTIONS, UPGRADE_FIELDS, action_mask, decode, random_legal, stage_indices
from .belief import p_next_live, p_next_live_naive

PLAY_KEYS = {"max_health", "players", "turn", "session_no", "lives_init", "blanks_init", "rounds_remaining",
             "lives_shot", "blanks_shot", "ejections", "next_round"}
PICK_KEYS = {"max_health", "players", "turn", "session_no", "available_upgrades"}
MAX_ACTIONS = 300


def observe(state: api.GameState) -> Any:
    return api.play_observation(state) if state.stage == Stage.PLAY else api.upgrade_observation(state)


def apply(state: api.GameState, action: Any) -> None:
    (api.step_PLAY if state.stage == Stage.PLAY else api.step_PICK_UPGRADE)(state, action)


def check_invariants(state: api.GameState) -> List[str]:
    errors = []
    k = len(state.players)
    healths = [p.health for p in state.players]
    if any(not 0 <= h <= state.max_health for h in healths):
        errors.append(f"health out of bounds {healths}")
    for i, p in enumerate(state.players):
        counts = [getattr(p.upgrades, f) for f in UPGRADE_FIELDS]
        if min(counts) < 0 or sum(counts) > 15:
            errors.append(f"player {i} inventory {counts}")
    alive = sum(h > 0 for h in healths)
    if state.alive_players != alive:
        errors.append(f"alive_players {state.alive_players} but {alive} have health")
    dead = {i for i, h in enumerate(healths) if h <= 0}
    if len(state.elimination_order) != len(set(state.elimination_order)) or set(state.elimination_order) != dead:
        errors.append(f"elimination_order {state.elimination_order} vs dead {sorted(dead)}")
    if state.game_over != (alive <= 1):
        errors.append(f"game_over={state.game_over} with {alive} alive")
    if not state.game_over and healths[state.turn] <= 0:
        errors.append(f"turn {state.turn} belongs to a dead player")
    if state.damage < 1:
        errors.append(f"damage {state.damage}")
    views = state.player_ejection_view
    ejected = {v.lives_ejected + v.blanks_ejected + v.unknowns_ejected for v in views}
    if len(ejected) != 1:
        errors.append("players disagree on how many shells were ejected")
    total_ejected = ejected.pop() if len(ejected) == 1 else 0
    known_ejected = sum(v.lives_ejected + v.blanks_ejected for v in views)
    if known_ejected != total_ejected:
        errors.append("an ejected shell is known to zero or several players")
    used = len(state.round_contents) - state.rounds_remaining
    if state.lives_shot + state.blanks_shot + total_ejected != used:
        errors.append("shells shot + ejected != shells used")
    lives_used = state.lives_shot + sum(v.lives_ejected for v in views)
    if sum(state.round_contents[:used]) != lives_used or sum(state.round_contents) != state.lives_init:
        errors.append("live shells not conserved")
    if state.stage == Stage.PICK_UPGRADE and min(getattr(state.available_upgrades, f) for f in UPGRADE_FIELDS) < 0:
        errors.append("negative available upgrades")
    return errors


def check_mask(state: api.GameState, obs: Any) -> List[str]:
    errors = []
    mask = action_mask(obs)
    in_stage = stage_indices(obs)
    for index in range(N_ACTIONS):
        if index not in in_stage:
            if mask[index]:
                errors.append(f"action {index} allowed outside its stage")
            continue
        trial = copy.deepcopy(state)
        try:
            apply(trial, decode(index, obs))
            ok = True
        except ValueError:
            ok = False
        except Exception as exc:  # anything but ValueError escapes run_match's illegal handling
            errors.append(f"action {index} raised {exc!r}")
            continue
        if ok != mask[index]:
            errors.append(f"action {index}: mask says {mask[index]}, engine says {ok}")
    return errors


def check_no_leak(state: api.GameState, obs: Any, revealer: Any, rng: random.Random) -> List[str]:
    errors = []
    data = wire.to_wire(obs)
    if set(data) != (PLAY_KEYS if state.stage == Stage.PLAY else PICK_KEYS):
        errors.append(f"observation fields {sorted(data)}")
    if state.stage != Stage.PLAY:
        return errors
    if obs.next_round != NextRound.UNKNOWN and revealer != state.turn:
        errors.append(f"next_round visible to {state.turn}, revealed by {revealer}")
    used = len(state.round_contents) - state.rounds_remaining
    start = used + (obs.next_round != NextRound.UNKNOWN)  # a revealed next shell stays put
    shuffled = copy.deepcopy(state)
    tail = shuffled.round_contents[start:]
    rng.shuffle(tail)
    shuffled.round_contents[start:] = tail
    if wire.to_wire(observe(shuffled)) != data:
        errors.append("observation depends on the unfired shell order")
    return errors


def play_game(seed: int, k: int, mask_every: int, stats: Counter, bias: Dict[str, List[float]]) -> List[str]:
    """One random legal game with every check. Returns violations (prefixed with seed and step)."""
    state = api.initGame(seed, k)
    rng, leak_rng = random.Random(seed * 7919 + k), random.Random(seed)
    errors: List[str] = []
    revealer = None
    step = 0
    while not state.game_over and step < MAX_ACTIONS:
        step += 1
        obs = observe(state)
        found = check_no_leak(state, obs, revealer, leak_rng)
        if step % mask_every == 0:
            found += check_mask(state, obs)
            stats["mask_checks"] += len(stage_indices(obs))
        action = random_legal(obs, rng)
        if state.stage == Stage.PLAY:
            used = len(state.round_contents) - state.rounds_remaining
            p_exact = p_next_live(obs)
            if 0.0 < p_exact < 1.0 and obs.ejections.unknowns_ejected == 0:
                bias["naive"].append(p_next_live_naive(obs))
                bias["exact"].append(p_exact)
                bias["outcome"].append(float(state.round_contents[used]))
            if action.action == ActionType.USE_UPGRADE and action.useUpgrade == UpgradeType.MAG_GLASS:
                revealer = state.turn
        floaties = [p.has_pool_floatie_on for p in state.players]
        stage, remaining = state.stage, state.rounds_remaining
        try:
            apply(state, action)
        except Exception as exc:
            found.append(f"legal action {wire.to_wire(action)} raised {exc!r}")
            errors += [f"seed {seed} k={k} step {step}: {e}" for e in found]
            break
        if state.stage == Stage.PICK_UPGRADE:  # a skip used up while choosing who picks next
            stats["floatie_spent_in_pick_stage"] += sum(a and not p.has_pool_floatie_on
                                                       for a, p in zip(floaties, state.players))
        if state.rounds_remaining != remaining or state.stage != stage:
            revealer = None
        found += check_invariants(state)
        stats["steps"] += 1
        errors += [f"seed {seed} k={k} step {step}: {e}" for e in found]
        if errors:
            break
    stats["games"] += 1
    stats["max_actions_reached"] += not state.game_over
    return errors


def trajectory_hash(seed: int, k: int) -> str:
    state, rng = api.initGame(seed, k), random.Random(seed)
    digest = hashlib.sha256()
    for _ in range(MAX_ACTIONS):
        if state.game_over:
            break
        obs = observe(state)
        digest.update(json.dumps(wire.to_wire(obs), sort_keys=True).encode())
        apply(state, random_legal(obs, rng))
    return digest.hexdigest()


def generator_report(rounds: int = 20000) -> Dict[str, Any]:
    """Sample fresh guns. Among guns with >= 60% live shells, how often is the first shell live?"""
    first_live = live_fraction = heavy = last_is_majority = unequal = 0
    for seed in range(rounds):
        state = api.initGame(seed, 2 + seed % 3)
        state.session_no = seed % 4
        state.rng = random.Random(seed)
        api._setup_round(state)
        lives, blanks = state.lives_init, state.blanks_init
        if lives / (lives + blanks) >= 0.6:
            heavy += 1
            first_live += state.round_contents[0]
            live_fraction += lives / (lives + blanks)
        if lives != blanks:
            unequal += 1
            last_is_majority += state.round_contents[-1] == (lives > blanks)
    return {"rounds": rounds, "live_heavy_guns": heavy,
            "live_heavy_first_shell_live_rate": first_live / heavy,
            "live_heavy_mean_live_fraction": live_fraction / heavy,
            "last_shell_is_majority_kind_rate": last_is_majority / unequal}


def brier(pred: List[float], outcome: List[float]) -> float:
    return sum((p - o) ** 2 for p, o in zip(pred, outcome)) / len(outcome)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=200, help="games per player count")
    ap.add_argument("--players", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--mask-every", type=int, default=1, help="check the mask on every Nth step")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args()

    stats: Counter = Counter()
    bias: Dict[str, List[float]] = {"naive": [], "exact": [], "outcome": []}
    errors: List[str] = []
    for k in args.players:
        for seed in range(args.seeds):
            errors += play_game(seed, k, args.mask_every, stats, bias)
    nondeterministic = [(s, k) for k in args.players for s in range(min(args.seeds, 50))
                        if trajectory_hash(s, k) != trajectory_hash(s, k)]
    errors += [f"seed {s} k={k}: trajectory differs between identical runs" for s, k in nondeterministic]

    outcomes = bias["outcome"]
    report = {
        "games": stats["games"], "steps": stats["steps"], "mask_checks": stats["mask_checks"],
        "max_actions_reached": stats["max_actions_reached"],
        "floatie_spent_in_pick_stage": stats["floatie_spent_in_pick_stage"],
        "violations": len(errors),
        "determinism_pairs_checked": min(args.seeds, 50) * len(args.players),
        "states_with_both_kinds_left": len(outcomes),
        "next_shell_live_rate": sum(outcomes) / len(outcomes),
        "mean_naive_p": sum(bias["naive"]) / len(outcomes),
        "brier_naive": brier(bias["naive"], outcomes),
        "brier_exact": brier(bias["exact"], outcomes),
        "generator": generator_report(),
    }
    for line in errors[:20]:
        print("VIOLATION", line)
    print(json.dumps(report, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(dict(report, errors=errors), f, indent=2)
    print("OK" if not errors else f"FAILED: {len(errors)} violations")
    sys.exit(bool(errors))


if __name__ == "__main__":
    main()
