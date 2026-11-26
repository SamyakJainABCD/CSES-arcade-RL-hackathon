"""Grade a task workspace with hidden tests that never enter the workspace.

    python -m benchmarks.coding_agent.grade --task T1 --workspace /tmp/ws_t1 [--json result.json]
    python -m benchmarks.coding_agent.grade --task T3 --calibrate      # measure the T3 threshold

Every grade first rebuilds the pristine workspace and compares sha256 hashes of the protected
public files; any edit fails the grade. Candidate code always runs in a separate interpreter
(`python -I`), against the grader's own engine copy:
  T1  answers on states from real games (hidden seeds) vs the exact reference, tolerance 1e-9
  T2  the pre-fix engine + candidate game_API.py: bad floatie targets 99/-1/-5/True/3 must raise
      ValueError with the state untouched, run_match must record `illegal` faults rather than
      crash, and full match logs on fixed seeds must hash identically to the original engine
  T3  candidate my_bot vs greedy_bot through engine.run_match on hidden seeds, both seatings;
      the win rate must reach the calibrated threshold
Exit code 0 on pass.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from .common import HERE, REPO, build_workspace, task_name, tampered

sys.path.insert(0, REPO)

HIDDEN = os.path.join(HERE, "hidden")


def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _run(cmd, cwd: str, timeout: float) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


# --- T1 ---------------------------------------------------------------------------------------
def t1_states(config: dict) -> list:
    """PLAY observations from real games, without unknown ejections, deduplicated."""
    import game_API as api
    import wire
    from rlgym.loader import LoadedBot
    from schemas import Stage
    bots = [os.path.join(REPO, "bots", n) for n in ("belief_bot", "greedy_bot", "random_bot")]
    seen, states = set(), []
    for game in range(config["games"]):
        seed = config["seed_offset"] + game
        k = 2 + game % 3
        rng = random.Random(seed)
        players = [LoadedBot(rng.choice(bots)) for _ in range(k)]
        state = api.initGame(seed, k)
        for _ in range(300):
            if state.game_over:
                break
            bot = players[state.turn]
            if state.stage == Stage.PLAY:
                obs = api.play_observation(state)
                data = wire.to_wire(obs)
                key = json.dumps(data, sort_keys=True)
                if data["ejections"]["unknowns_ejected"] == 0 and key not in seen:
                    seen.add(key)
                    states.append(data)
                action = bot.play(obs)
                step = api.step_PLAY
            else:
                action, step = bot.pick_upgrade(api.upgrade_observation(state)), api.step_PICK_UPGRADE
            try:
                step(state, action)
            except ValueError:
                break
    random.Random(config["seed_offset"]).shuffle(states)
    return states[:config["max_states"]]


def grade_t1(workspace: str) -> Dict[str, Any]:
    from rlgym.belief import p_next_live
    config = _load(os.path.join(HIDDEN, "T1_belief", "config.json"))
    states = t1_states(config)
    with tempfile.TemporaryDirectory() as tmp:
        states_path, out_path = os.path.join(tmp, "states.json"), os.path.join(tmp, "out.json")
        with open(states_path, "w") as f:
            json.dump(states, f)
        proc = _run([sys.executable, "-I", "-B", os.path.join(HIDDEN, "T1_belief", "harness.py"), os.path.abspath(workspace),
                     states_path, out_path], cwd=workspace, timeout=120)
        if not os.path.exists(out_path):
            return {"passed": False, "reason": "harness produced no output", "stderr": proc.stderr[-1500:]}
        result = _load(out_path)
    if result["import_error"]:
        return {"passed": False, "reason": f"import failed: {result['import_error']}"}
    wrong = []
    for state, answer in zip(states, result["answers"]):
        expected = p_next_live(state)
        if not isinstance(answer, float) or abs(answer - expected) > config["tolerance"]:
            wrong.append({"expected": expected, "got": answer, "state": state})
    both_left = sum(1 for s in states if 0 < p_next_live(s) < 1)
    return {"passed": not wrong, "states": len(states), "states_with_both_kinds_left": both_left,
            "wrong": len(wrong), "first_wrong": wrong[:2]}


# --- T2 ---------------------------------------------------------------------------------------
def _t2_dir(root: str, game_api: str) -> str:
    """A grading directory: pristine pre-fix engine, baseline and red-team bots, the given game_API.py."""
    build_workspace("T2", root)
    shutil.copy2(game_api, os.path.join(root, "game_API.py"))
    for name in ("greedy_bot",):
        shutil.copytree(os.path.join(REPO, "bots", name), os.path.join(root, "bots", name),
                        ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("floatie_99", "floatie_neg1"):
        shutil.copytree(os.path.join(REPO, "redteam", "bots", name), os.path.join(root, "bots", name),
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(os.path.join(HIDDEN, "T2_bugfix", "check.py"), os.path.join(root, "check.py"))
    return root


def _check(root: str, mode: str) -> Any:
    proc = _run([sys.executable, "-I", "-B", "check.py", mode], cwd=root, timeout=300)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": proc.stderr[-1500:]}


def grade_t2(workspace: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        original = _t2_dir(os.path.join(tmp, "original"),
                           os.path.join(HERE, "tasks", "T2_bugfix", "game_API.py"))
        candidate = _t2_dir(os.path.join(tmp, "candidate"), os.path.join(workspace, "game_API.py"))
        floatie = _check(candidate, "floatie")
        expected, got = _check(original, "hashes"), _check(candidate, "hashes")
    if "error" in floatie or "error" in got:
        return {"passed": False, "reason": "check crashed", "detail": floatie.get("error") or got.get("error")}
    regressions = sorted(k for k in expected if got.get(k) != expected[k])
    failed = sorted(k for k, v in floatie.items() if not v["ok"])
    return {"passed": not regressions and not failed, "floatie_checks": floatie, "failed_checks": failed,
            "regression_matches": len(expected), "regressions": regressions}


# --- T3 ---------------------------------------------------------------------------------------
def t3_win_rate(bot_dir: str, seed_offset: int, seeds: int, workers: int = 4) -> Dict[str, Any]:
    from engine.limits import Limits, submission_problems
    from engine.run_match import Submission, run_match
    problems = submission_problems(bot_dir, Limits())
    if problems:
        return {"matches": 0, "win_rate": 0.0, "problems": problems}
    me, greedy = Submission("candidate", bot_dir), Submission("greedy_bot", os.path.join(REPO, "bots", "greedy_bot"))
    jobs = [(seed, seat) for seed in range(seed_offset, seed_offset + seeds) for seat in (0, 1)]

    def play(job):
        seed, seat = job
        seats = [me, greedy] if seat == 0 else [greedy, me]
        summary = run_match(seats, seed, backend="local")
        return summary["placements"][seat] == 1, summary["faults"][seat]

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(play, jobs))
    wins = sum(win for win, _ in results)
    faults: Dict[str, int] = {}
    for _, f in results:
        for kind, n in f.items():
            faults[kind] = faults.get(kind, 0) + n
    return {"matches": len(jobs), "wins": wins, "win_rate": round(wins / len(jobs), 4), "faults": faults}


def grade_t3(workspace: str) -> Dict[str, Any]:
    config = _load(os.path.join(HIDDEN, "T3_bot", "config.json"))
    with tempfile.TemporaryDirectory() as tmp:
        bot_dir = os.path.join(tmp, "my_bot")
        shutil.copytree(os.path.join(workspace, "my_bot"), bot_dir, ignore=shutil.ignore_patterns("__pycache__"))
        result = t3_win_rate(bot_dir, config["seed_offset"], config["seeds"])
    result["threshold"] = config["threshold"]
    result["passed"] = result["matches"] > 0 and result["win_rate"] >= config["threshold"]
    return result


def calibrate_t3() -> Dict[str, Any]:
    """belief_bot's engine win rate on public calibration seeds, minus two standard errors at the hidden n."""
    config = _load(os.path.join(HIDDEN, "T3_bot", "config.json"))
    measured = t3_win_rate(os.path.join(REPO, "bots", "belief_bot"), 0, config["calibration_seeds"])
    p, n_hidden = measured["win_rate"], 2 * config["seeds"]
    margin = 2 * (p * (1 - p) / n_hidden) ** 0.5
    return dict(measured, hidden_matches=n_hidden, margin=round(margin, 4),
                suggested_threshold=int((p - margin) * 100) / 100)


GRADERS = {"T1": grade_t1, "T2": grade_t2, "T3": grade_t3}


def grade(task: str, workspace: str) -> Dict[str, Any]:
    key = task_name(task)
    with tempfile.TemporaryDirectory() as pristine:
        build_workspace(key, pristine)
        edits = tampered(key, workspace, pristine)
    if edits:
        return {"task": key, "passed": False, "reason": "protected files edited", "tampered": edits}
    try:
        result = GRADERS[key](workspace)
    except subprocess.TimeoutExpired as exc:
        result = {"passed": False, "reason": f"timeout: {exc}"}
    return dict(result, task=key)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--workspace")
    ap.add_argument("--calibrate", action="store_true", help="T3 only: measure the reference win rate")
    ap.add_argument("--json", help="write the result here")
    args = ap.parse_args()
    if args.calibrate:
        result = calibrate_t3()
    elif not args.workspace:
        ap.error("--workspace is required")
    else:
        result = grade(args.task, args.workspace)
    text = json.dumps(result, indent=2, default=str)
    print(text if len(text) < 6000 else text[:6000] + "\n... (truncated; use --json)")
    if args.json:
        with open(args.json, "w") as f:
            f.write(text)
    sys.exit(0 if result.get("passed", True) else 1)


if __name__ == "__main__":
    main()
