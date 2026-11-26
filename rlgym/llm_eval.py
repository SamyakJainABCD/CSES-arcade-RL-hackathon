"""Evaluate the language-model player (agents/llm_bot) against a baseline bot.

    python -m rlgym.llm_eval [--provider mock|anthropic|openai] [--model ID] [--seeds 20]
                             [--opponent bots/greedy_bot] [--out out/llm_eval]

Plays every seed in both seatings, in-process (the model needs the network, which the sandbox
denies). Reports the win rate with a Wilson 95% interval, the parse-failure rate, the
illegal-action rate (engine faults per LLM decision), blunder rates from rlgym.analysis,
token usage and latency. Every prompt and response is logged to OUT/prompts.jsonl.
"""
import argparse
import json
import os
import time

from .analysis import analyze
from .loader import LoadedBot
from .rollout import play_match
from .stats import wilson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_BOT = os.path.join(ROOT, "agents", "llm_bot")


def run(provider: str, model: str, seeds: int, opponent: str, out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    prompts, traj_path = os.path.join(out, "prompts.jsonl"), os.path.join(out, "trajectories.jsonl")
    open(prompts, "w").close()
    params = {"provider": provider, "model": model, "log": prompts}
    totals = {"calls": 0, "parse_failures": 0, "off_list": 0, "input_tokens": 0, "output_tokens": 0,
              "provider_errors": 0, "seconds": 0.0}
    wins = matches = illegal = invalid = dq = points = 0
    with open(traj_path, "w") as traj_file:
        for seed in range(seeds):
            for llm_seat in (0, 1):
                llm = LoadedBot(LLM_BOT, params=dict(params), name="llm_bot")
                other = LoadedBot(opponent)
                seats = [llm, other] if llm_seat == 0 else [other, llm]
                names = ["llm_bot", other.name] if llm_seat == 0 else [other.name, "llm_bot"]
                traj = []
                summary = play_match(seats, names, seed, match_id=f"s{seed}_llm{llm_seat}", trajectory=traj)
                traj_file.writelines(json.dumps(r) + "\n" for r in traj)
                for key in totals:
                    totals[key] += llm.bot.stats[key]
                matches += 1
                wins += summary["placements"][llm_seat] == 1
                points += 1 if summary["placements"][llm_seat] == 1 else -1
                illegal += summary["faults"][llm_seat].get("illegal", 0)
                invalid += summary["faults"][llm_seat].get("invalid", 0) + summary["faults"][llm_seat].get("error", 0)
                dq += summary["disqualified"][llm_seat]
    low, high = wilson(wins, matches)
    calls = max(1, totals["calls"])
    blunders = analyze([traj_path]).get("llm_bot", {})
    return {
        "provider": provider, "model": model, "opponent": os.path.basename(os.path.normpath(opponent)),
        "matches": matches, "win_rate": round(wins / matches, 4), "win_rate_ci95": [round(low, 4), round(high, 4)],
        "avg_points": round(points / matches, 4), "llm_decisions": totals["calls"],
        "parse_failure_rate": round(totals["parse_failures"] / calls, 4),
        "off_list_rate": round(totals["off_list"] / calls, 4),
        "illegal_action_rate": round(illegal / calls, 4), "other_fault_count": invalid, "disqualified": dq,
        "provider_errors": totals["provider_errors"],
        "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
        "tokens_estimated": provider == "mock", "mean_latency_s": round(totals["seconds"] / calls, 4),
        "blunders": {k: v for k, v in blunders.items() if isinstance(v, dict) or k == "blunders_per_100_decisions"},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="mock", choices=["mock", "anthropic", "openai"])
    ap.add_argument("--model")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--opponent", default=os.path.join(ROOT, "bots", "greedy_bot"))
    ap.add_argument("--out", default="out/llm_eval")
    args = ap.parse_args()
    key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(args.provider)
    if key and not os.environ.get(key):
        ap.error(f"{key} is not set; use --provider mock for an offline run")
    started = time.time()
    result = run(args.provider, args.model, args.seeds, args.opponent, args.out)
    result["seconds"] = round(time.time() - started, 2)
    print(json.dumps(result, indent=2))
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
