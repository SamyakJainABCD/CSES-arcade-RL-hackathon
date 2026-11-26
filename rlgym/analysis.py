"""Trajectory analysis: how often does each bot make a provably bad or wasted move?

    python -m rlgym.analysis out/rollout/trajectories.jsonl      # rollout output
    python -m rlgym.analysis out/                                # engine tournament (out/logs/*.jsonl)

Works on any JSONL made of decision records (seat, stage, obs, action) followed by a {"summary"}
line per match. That covers both rollout trajectories and engine match logs. Beliefs are
recomputed from the logged observation, so engine logs need no extra fields.

Counted per bot, over its PLAY decisions:
  self_known_live      shot itself after the magnifying glass showed LIVE
  self_certain_live    shot itself when the exact belief is 1 (includes the above)
  opp_known_blank      shot an opponent after the glass showed BLANK
  opp_certain_blank    shot an opponent when the exact belief is 0
  redundant_mag_glass  used the glass when the next shell was already known or certain
  juice_full_health    drank juice at full health
  against_belief       shot itself with p > 0.5, or an opponent with p < 0.5 (exact belief)
  self_at_coin_flip    shot itself with p == 0.5 exactly (risks 1 health to keep the turn)
"""
import argparse
import glob
import json
import os
from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, Tuple

from .belief import p_next_live

METRICS = {  # metric -> denominator
    "self_known_live": "shots", "self_certain_live": "shots", "opp_known_blank": "shots",
    "opp_certain_blank": "shots", "against_belief": "shots", "self_at_coin_flip": "shots",
    "redundant_mag_glass": "mag_glass_uses", "juice_full_health": "juice_uses",
}


def iter_files(paths: Iterable[str]) -> Iterator[str]:
    for path in paths:
        if os.path.isdir(path):
            logs = os.path.join(path, "logs")
            yield from sorted(glob.glob(os.path.join(logs if os.path.isdir(logs) else path, "*.jsonl")))
        else:
            yield path


def iter_decisions(paths: Iterable[str]) -> Iterator[Tuple[str, dict]]:
    """(bot name, decision record) for every decision in matches that have a summary."""
    for path in iter_files(paths):
        pending: List[dict] = []
        with open(path) as f:
            for line in f:
                record = json.loads(line)
                if "summary" not in record:
                    pending.append(record)
                    continue
                summary = record["summary"]
                names = summary.get("models") or summary["seats"]
                for decision in pending:
                    if decision.get("stage") == "PLAY" and decision.get("action") and "obs" in decision:
                        yield names[decision["seat"]], decision
                pending = []


def classify(decision: dict) -> Dict[str, int]:
    """Counters for one PLAY decision."""
    obs, action = decision["obs"], decision["action"]
    me = obs["turn"]
    p = decision.get("p_live", p_next_live(obs))
    known = obs["next_round"]
    c: Dict[str, int] = defaultdict(int)
    c["decisions"] = 1
    if action["action"] == "SHOOT":
        c["shots"] = 1
        self_shot = action["target"] == me
        if self_shot:
            c["self_known_live"] = known == "LIVE"
            c["self_certain_live"] = p == 1.0
            c["against_belief"] = p > 0.5
            c["self_at_coin_flip"] = p == 0.5
        else:
            c["opp_known_blank"] = known == "BLANK"
            c["opp_certain_blank"] = p == 0.0
            c["against_belief"] = p < 0.5
    elif action["useUpgrade"] == "MAG_GLASS":
        c["mag_glass_uses"] = 1
        c["redundant_mag_glass"] = known != "UNKNOWN" or p in (0.0, 1.0)
    elif action["useUpgrade"] == "JUICE":
        c["juice_uses"] = 1
        c["juice_full_health"] = obs["players"][me]["health"] >= obs["max_health"]
    return c


def analyze(paths: Iterable[str]) -> Dict[str, dict]:
    totals: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name, decision in iter_decisions(paths):
        for key, value in classify(decision).items():
            totals[name][key] += int(value)
    report = {}
    for name, t in sorted(totals.items()):
        row = {key: t[key] for key in ("decisions", "shots", "mag_glass_uses", "juice_uses")}
        for metric, denom in METRICS.items():
            row[metric] = {"count": t[metric], "rate": round(t[metric] / t[denom], 4) if t[denom] else 0.0}
        row["blunders_per_100_decisions"] = round(100 * sum(t[m] for m in (
            "self_certain_live", "opp_certain_blank", "redundant_mag_glass", "juice_full_health")) / t["decisions"], 3)
        report[name] = row
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="trajectory .jsonl files, log files, or tournament out/ dirs")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args()
    report = analyze(args.paths)
    header = ["bot", "decisions"] + list(METRICS) + ["blunders/100"]
    print(" | ".join(header))
    for name, row in report.items():
        cells = [name, str(row["decisions"])] + [f"{row[m]['rate']:.3f}" for m in METRICS]
        print(" | ".join(cells + [str(row["blunders_per_100_decisions"])]))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
