"""Run every red-team bot through the real engine and check it is contained.

    python -m redteam.run [--seeds 6] [--eval-seeds 200] [--engine-seeds 40] [--json report.json]

1. Fault containment: each adversarial bot plays engine.run_match (local backend) against
   random_bot. The engine must return a summary, record the expected fault kind for the
   adversary only, and disqualify it where the rules say so.
2. Memory peeking: gc_peeker reads the hidden GameState. Compare its win rate against
   greedy_bot in-process (rlgym.rollout) and out-of-process (engine.run_match).
3. Stalling: staller is belief_bot plus clock-burning when ahead. On the same seeds, how
   often does it reach the 300-action cap, and how often does the outcome change?
4. Reward hacking: in a 4-player table, does ranking by damage dealt (NaiveDamageReward)
   agree with ranking by placement points (the leaderboard)?
Exit code 1 if any containment check fails.
"""
import argparse
import json
import os
import sys
import time
from typing import Dict, List

from engine.run_match import Submission, run_match
from rlgym.loader import LoadedBot
from rlgym.rollout import evaluate, play_match
from rlgym.stats import wilson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RED = os.path.join(ROOT, "redteam", "bots")
BOTS = os.path.join(ROOT, "bots")

# bot -> (fault kinds allowed for it, must it be disqualified whenever it faults?)
EXPECTED = {
    "floatie_99": ({"illegal"}, False),
    "floatie_neg1": ({"illegal"}, False),
    "floatie_true": ({"invalid"}, False),
    "raiser": ({"error"}, False),
    "sleeper": ({"timeout"}, False),
    "slow_init": ({"crash"}, True),
    "garbage_action": ({"error"}, False),
    "garbage_line": ({"invalid"}, False),
    "huge_line": ({"crash"}, True),
}


def containment(seeds: int) -> List[dict]:
    rows = []
    opponent = Submission("random_bot", os.path.join(BOTS, "random_bot"))
    for name, (kinds, fatal) in EXPECTED.items():
        adversary = Submission(name, os.path.join(RED, name))
        seen: Dict[str, int] = {}
        dq = matches = opponent_faults = 0
        problems = []
        started = time.time()
        for seed in range(seeds):
            try:
                summary = run_match([adversary, opponent], seed, backend="local")
            except Exception as exc:  # the engine itself failed: the worst outcome
                problems.append(f"seed {seed}: run_match raised {exc!r}")
                continue
            matches += 1
            for kind, count in summary["faults"][0].items():
                seen[kind] = seen.get(kind, 0) + count
            opponent_faults += sum(summary["faults"][1].values())
            dq += summary["disqualified"][0]
            if summary["faults"][0] and fatal and not summary["disqualified"][0]:
                problems.append(f"seed {seed}: fatal fault without disqualification")
        if not seen:
            problems.append("adversary never faulted")
        if set(seen) - kinds:
            problems.append(f"unexpected fault kinds {sorted(set(seen) - kinds)}")
        if opponent_faults:
            problems.append(f"opponent picked up {opponent_faults} faults")
        rows.append({"bot": name, "expected": sorted(kinds), "faults": seen, "matches": matches,
                     "disqualified": dq, "seconds": round(time.time() - started, 1),
                     "ok": not problems, "problems": problems})
    return rows


def engine_win_rate(bot: str, opponent: str, seeds: int) -> dict:
    """Head-to-head through the sandboxed engine, both seatings per seed."""
    a, b = Submission("a", bot), Submission("b", opponent)
    wins = n = 0
    for seed in range(seeds):
        for seats, mine in (([a, b], 0), ([b, a], 1)):
            wins += run_match(seats, seed, backend="local")["placements"][mine] == 1
            n += 1
    low, high = wilson(wins, n)
    return {"matches": n, "win_rate": round(wins / n, 4), "win_rate_ci95": [round(low, 4), round(high, 4)]}


def peeking(eval_seeds: int, engine_seeds: int) -> dict:
    peeker, belief, greedy = (os.path.join(RED, "gc_peeker"), os.path.join(BOTS, "belief_bot"),
                              os.path.join(BOTS, "greedy_bot"))
    in_process = evaluate([peeker, greedy], eval_seeds)["bots"]["gc_peeker"]
    baseline = evaluate([belief, greedy], eval_seeds)["bots"]["belief_bot"]
    return {
        "in_process_vs_greedy": {k: in_process[k] for k in ("matches", "win_rate", "win_rate_ci95")},
        "belief_bot_in_process_vs_greedy": {k: baseline[k] for k in ("matches", "win_rate", "win_rate_ci95")},
        "engine_vs_greedy": engine_win_rate(peeker, greedy, engine_seeds),
        "belief_bot_engine_vs_greedy": engine_win_rate(belief, greedy, engine_seeds),
    }


def paired(bot: str, control: str, opponent: str, seeds: int, players: int = 2) -> dict:
    """Play `bot` and `control` in the same seat against the same opponents and compare."""
    rows = {"matches": 0, "bot_max_actions": 0, "control_max_actions": 0, "placement_changed": 0,
            "bot_better": 0, "bot_worse": 0, "won_at_cap": 0}
    for seed in range(seeds):
        for seat in range(players):
            def table(me):
                paths = [opponent] * players
                paths[seat] = me
                return play_match([LoadedBot(p) for p in paths], [f"s{i}" for i in range(players)], seed)
            test, ctrl = table(bot), table(control)
            rows["matches"] += 1
            rows["bot_max_actions"] += test["reason"] == "max_actions"
            rows["control_max_actions"] += ctrl["reason"] == "max_actions"
            rows["won_at_cap"] += test["reason"] == "max_actions" and test["placements"][seat] == 1
            delta = ctrl["placements"][seat] - test["placements"][seat]
            rows["placement_changed"] += delta != 0
            rows["bot_better"] += delta > 0
            rows["bot_worse"] += delta < 0
    return rows


def reward_hacking(seeds: int) -> dict:
    """Four-player table: rank bots by damage dealt (NaiveDamageReward) and by placement points."""
    paths = [os.path.join(BOTS, "belief_bot"), os.path.join(BOTS, "greedy_bot"), os.path.join(BOTS, "random_bot"),
             os.path.join(RED, "damage_farmer")]
    rows = evaluate(paths, seeds)["bots"]
    table = {name: {k: row[k] for k in ("matches", "win_rate", "win_rate_ci95", "avg_points", "avg_damage_dealt")}
             for name, row in rows.items()}
    by_damage = sorted(table, key=lambda n: -table[n]["avg_damage_dealt"])
    by_points = sorted(table, key=lambda n: -table[n]["avg_points"])
    inversions = [(a, b) for i, a in enumerate(by_damage) for b in by_damage[i + 1:]
                  if by_points.index(a) > by_points.index(b)]
    return {"table": table, "rank_by_damage": by_damage, "rank_by_points": by_points,
            "inverted_pairs": inversions}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=6, help="engine matches per adversarial bot")
    ap.add_argument("--eval-seeds", type=int, default=200, help="seeds for in-process comparisons")
    ap.add_argument("--engine-seeds", type=int, default=40, help="seeds for out-of-process win rates")
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args()

    report = {"containment": containment(args.seeds)}
    for row in report["containment"]:
        status = "OK  " if row["ok"] else "FAIL"
        print(f"{status} {row['bot']:15} expected {row['expected']} got {row['faults']} "
              f"DQ {row['disqualified']}/{row['matches']} ({row['seconds']}s) {'; '.join(row['problems'])}")
    report["peeking"] = peeking(args.eval_seeds, args.engine_seeds)
    staller, belief, greedy = (os.path.join(RED, "staller"), os.path.join(BOTS, "belief_bot"),
                               os.path.join(BOTS, "greedy_bot"))
    report["stalling"] = {f"{k}p_vs_greedy": paired(staller, belief, greedy, args.eval_seeds, k) for k in (2, 4)}
    report["reward_hacking"] = reward_hacking(max(1, args.eval_seeds // 2))
    print(json.dumps({k: v for k, v in report.items() if k != "containment"}, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
    failed = [row["bot"] for row in report["containment"] if not row["ok"]]
    print("OK: engine contained every adversarial bot" if not failed else f"FAILED: {failed}")
    sys.exit(bool(failed))


if __name__ == "__main__":
    main()
