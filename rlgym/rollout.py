"""Fast in-process evaluation: every seating of the given bots on every seed.

    python -m rlgym.rollout bots/belief_bot bots/greedy_bot --seeds 200 [--out out/rollout]

Faults work as in engine.run_match: error, invalid and illegal are strikes, the engine's fallback
move is played, and two strikes disqualify. In-process code cannot be preempted, so decisions over
the engine's 50 ms limit are flagged instead of timed out. Writes trajectories.jsonl (one record
per decision: obs, action, legal mask, exact and naive belief, fault, time; then a {"summary"}
line per match, the same shape as engine logs) and summary.json.

Run untrusted bots through engine.run_match. In-process bots can read the hidden game state
(see redteam/).
"""
import argparse
import itertools
import json
import os
import random
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import game_API as api
import wire
from engine.limits import Limits
from engine.run_match import FATAL_FAULTS, _fallback_pick, _fallback_play, _placements
from engine.scoring import placement_points
from schemas import *

from .actions import action_mask
from .belief import p_next_live, p_next_live_naive
from .loader import LoadedBot
from .stats import wilson


class Fault(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind, self.detail = kind, detail


def decide(bot: Any, state: api.GameState, obs: Any) -> Any:
    """Ask a bot for an action and validate it the way the sandbox and engine do."""
    play = state.stage == Stage.PLAY
    try:
        reply = bot.play(obs) if play else bot.pick_upgrade(obs)
        data = wire.action_play_to_wire(reply) if play else wire.action_pick_to_wire(reply)
    except Exception as exc:
        raise Fault("error", repr(exc))
    try:
        action = wire.action_play_from_wire(data) if play else wire.action_pick_from_wire(data)
    except (KeyError, ValueError, TypeError) as exc:
        raise Fault("invalid", repr(exc))
    return data, action


def play_match(seats: List[Any], names: List[str], seed: int, limits: Limits = Limits(),
               match_id: str = "", trajectory: Optional[list] = None) -> dict:
    """seats[i] is a bot object for player i. Returns an engine-style summary with extra stats."""
    k = len(seats)
    state = api.initGame(seed, k)
    fallback_rng = random.Random(seed ^ 0x5EED)
    strikes, faults, disqualified = [0] * k, [{} for _ in range(k)], [False] * k
    time_used, slow, max_ms, damage = [0.0] * k, [0] * k, [0.0] * k, [0] * k
    steps = 0
    while not state.game_over and steps < limits.max_actions:
        steps += 1
        seat, stage = state.turn, state.stage
        obs = api.play_observation(state) if stage == Stage.PLAY else api.upgrade_observation(state)
        before = [p.health for p in state.players]
        record: Dict[str, Any] = {"match_id": match_id, "seed": seed, "step": steps, "seat": seat,
                                  "bot": names[seat], "stage": stage.value}
        if trajectory is not None:
            record["obs"] = wire.to_wire(obs)
            record["legal"] = action_mask(obs)
            if stage == Stage.PLAY:
                record["p_live"], record["p_live_naive"] = p_next_live(obs), p_next_live_naive(obs)
        started = time.perf_counter()
        try:
            try:
                data, action = decide(seats[seat], state, obs)
            finally:
                elapsed = time.perf_counter() - started
                time_used[seat] += elapsed
                max_ms[seat] = max(max_ms[seat], elapsed * 1000)
                slow[seat] += elapsed > limits.move_timeout
                record["ms"] = round(elapsed * 1000, 3)
            record["action"] = data
            try:
                (api.step_PLAY if stage == Stage.PLAY else api.step_PICK_UPGRADE)(state, action)
            except ValueError as exc:
                raise Fault("illegal", str(exc))
            except Exception as exc:
                raise Fault("illegal", f"engine error: {exc!r}")
        except Fault as fault:
            record["fault"], record["detail"] = fault.kind, fault.detail[:500]
            faults[seat][fault.kind] = faults[seat].get(fault.kind, 0) + 1
            strikes[seat] += 1
            if fault.kind in FATAL_FAULTS or strikes[seat] >= limits.max_strikes:
                disqualified[seat] = True
                api.eliminate_player(state, seat)
            elif not state.game_over:
                if stage == Stage.PLAY:
                    api.step_PLAY(state, _fallback_play(state, fallback_rng))
                else:
                    api.step_PICK_UPGRADE(state, _fallback_pick(state))
        damage[seat] += sum(max(0, before[i] - p.health) for i, p in enumerate(state.players) if i != seat)
        if trajectory is not None:
            trajectory.append(record)
    placements = _placements(state)
    summary = {
        "match_id": match_id, "seed": seed, "seats": names, "placements": placements,
        "winner": placements.index(1), "reason": "last_alive" if state.game_over else "max_actions",
        "actions": steps, "faults": faults, "disqualified": disqualified,
        "time_used": [round(t, 4) for t in time_used], "final_health": [p.health for p in state.players],
        "slow_decisions": slow, "max_decision_ms": [round(m, 3) for m in max_ms], "damage_dealt": damage,
        "over_budget": [t > limits.bot_time_budget for t in time_used],
    }
    if trajectory is not None:
        trajectory.append({"summary": summary})
    return summary


def unique_names(paths: List[str]) -> List[str]:
    names, seen = [], defaultdict(int)
    for path in paths:
        base = os.path.basename(os.path.normpath(path))
        seen[base] += 1
        names.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return names


def evaluate(paths: List[str], seeds: int, seed_offset: int = 0, players: Optional[int] = None,
             trajectories: Optional[str] = None, limits: Limits = Limits(), loader=LoadedBot) -> dict:
    """Play every seating of the bots (padded by cycling if players > len(paths)) on every seed."""
    names = unique_names(paths)
    k = players or len(paths)
    lineup = [i % len(paths) for i in range(k)]
    out = open(trajectories, "w") if trajectories else None
    summaries = []
    try:
        for seed in range(seed_offset, seed_offset + seeds):
            for seating in sorted(set(itertools.permutations(lineup))):
                seat_names = [names[i] if lineup.count(i) == 1 else f"{names[i]}@{s}" for s, i in enumerate(seating)]
                bots = [loader(paths[i]) for i in seating]
                traj = [] if out else None
                match_id = f"s{seed}_p{''.join(map(str, seating))}"
                summary = play_match(bots, seat_names, seed, limits, match_id, traj)
                summary["models"] = [names[i] for i in seating]
                summaries.append(summary)
                if out:
                    out.writelines(json.dumps(r) + "\n" for r in traj)
    finally:
        if out:
            out.close()
    return summarize(summaries)


def summarize(summaries: List[dict]) -> dict:
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    for m in summaries:
        k = len(m["seats"])
        for seat, name in enumerate(m.get("models", m["seats"])):
            s = per[name]
            place = m["placements"][seat]
            s["matches"] += 1
            s["wins"] += place == 1
            s["points"] += placement_points(place, k)
            s["place"] += place
            s["damage"] += m["damage_dealt"][seat]
            s["slow_decisions"] += m["slow_decisions"][seat]
            s["over_budget"] += m["over_budget"][seat]
            s["max_decision_ms"] = max(s["max_decision_ms"], m["max_decision_ms"][seat])
            s["disqualified"] += m["disqualified"][seat]
            for kind, count in m["faults"][seat].items():
                s[f"fault_{kind}"] += count
    rows = {}
    for name, s in per.items():
        n = int(s["matches"])
        low, high = wilson(s["wins"], n)
        rows[name] = {"matches": n, "win_rate": round(s["wins"] / n, 4), "win_rate_ci95": [round(low, 4), round(high, 4)],
                      "avg_points": round(s["points"] / n, 4), "avg_place": round(s["place"] / n, 4),
                      "avg_damage_dealt": round(s["damage"] / n, 4),
                      "faults": {key[6:]: int(v) for key, v in s.items() if key.startswith("fault_")},
                      "disqualified": int(s["disqualified"]), "slow_decisions": int(s["slow_decisions"]),
                      "matches_over_budget": int(s["over_budget"]), "max_decision_ms": round(s["max_decision_ms"], 3)}
    reasons = defaultdict(int)
    for m in summaries:
        reasons[m["reason"]] += 1
    return {"matches": len(summaries), "reasons": dict(reasons), "bots": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bots", nargs="+", help="bot directories")
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--players", type=int, help="table size (default: number of bots)")
    ap.add_argument("--out", help="directory for trajectories.jsonl and summary.json")
    args = ap.parse_args()
    trajectories = None
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        trajectories = os.path.join(args.out, "trajectories.jsonl")
    started = time.time()
    result = evaluate(args.bots, args.seeds, args.seed_offset, args.players, trajectories)
    result["seconds"] = round(time.time() - started, 2)
    print(json.dumps(result, indent=2))
    if args.out:
        with open(os.path.join(args.out, "summary.json"), "w") as f:
            json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
