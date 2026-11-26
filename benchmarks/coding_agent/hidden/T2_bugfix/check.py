"""Runs inside a grading directory (cwd) holding the pristine pre-fix engine and a candidate game_API.py.

    python -I check.py hashes   -> sha256 of full match logs for baseline bots on fixed seeds
    python -I check.py floatie  -> bad floatie targets must be ValueError, state untouched, illegal faults
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.getcwd())
import game_API as api  # noqa: E402
from engine.run_match import Submission, run_match  # noqa: E402
from schemas import *  # noqa: E402,F403

LINEUPS = {2: ["random_bot", "greedy_bot"], 3: ["greedy_bot", "random_bot", "greedy_bot"],
           4: ["greedy_bot", "random_bot", "greedy_bot", "random_bot"]}


def hashes() -> dict:
    out = {}
    for k, names in LINEUPS.items():
        for seed in range(6):
            log = f"match_{k}_{seed}.jsonl"
            run_match([Submission(f"{n}{i}", os.path.join("bots", n)) for i, n in enumerate(names)], seed, log,
                      backend="local")
            digest = hashlib.sha256()
            with open(log) as f:
                for line in f:
                    record = json.loads(line)
                    record.get("summary", {}).pop("time_used", None)
                    digest.update(json.dumps(record, sort_keys=True).encode())
            out[f"{k}p_seed{seed}"] = digest.hexdigest()
    return out


def snapshot(state) -> str:
    return json.dumps([[p.health, p.has_pool_floatie_on, vars(p.upgrades)] for p in state.players]
                      + [state.turn, state.rounds_remaining, state.stage.value], sort_keys=True)


def floatie() -> dict:
    results = {}
    for target in (99, -1, -5, True, 3):
        state = api.initGame(7, 3)
        state.players[0].upgrades.pool_floatie = 1
        before = snapshot(state)
        action = Action_PLAY()
        action.action, action.useUpgrade, action.target = ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, target
        try:
            api.step_PLAY(state, action)
            outcome = "accepted"
        except ValueError:
            outcome = "ValueError"
        except Exception as exc:
            outcome = f"crash {exc!r}"
        results[f"direct target={target!r}"] = {"ok": outcome == "ValueError" and snapshot(state) == before,
                                                "outcome": outcome, "state_unchanged": snapshot(state) == before}
    state = api.initGame(7, 3)
    state.players[0].upgrades.pool_floatie = 1
    action = Action_PLAY()
    action.action, action.useUpgrade, action.target = ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, 2
    try:
        api.step_PLAY(state, action)
        results["direct valid target 2"] = {"ok": state.players[2].has_pool_floatie_on}
    except Exception as exc:
        results["direct valid target 2"] = {"ok": False, "outcome": repr(exc)}
    for bot in ("floatie_99", "floatie_neg1"):
        kinds, crashed = {}, None
        for seed in range(8):
            try:
                summary = run_match([Submission(bot, os.path.join("bots", bot)),
                                     Submission("random", os.path.join("bots", "random_bot"))], seed, backend="local")
            except Exception as exc:
                crashed = repr(exc)
                break
            for kind, n in summary["faults"][0].items():
                kinds[kind] = kinds.get(kind, 0) + n
        results[f"run_match {bot}"] = {"ok": crashed is None and set(kinds) == {"illegal"},
                                       "faults": kinds, "crash": crashed}
    return results


if __name__ == "__main__":
    print(json.dumps(hashes() if sys.argv[1] == "hashes" else floatie()))
