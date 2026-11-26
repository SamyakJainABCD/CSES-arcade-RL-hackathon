"""Run a coding agent (Claude Code, headless) on each task and grade every run.

    python -m benchmarks.coding_agent.run_agents --root out/agent_runs [--tasks T1 T2 T3] [--runs 3]
                                                 [--parallel 3] [--budget-usd 5] [--timeout 1800]

Each run gets a freshly prepared workspace and `claude -p "<task README>"` with the workspace as
its working directory. Edits are auto-accepted and Bash is limited to python/ls. The full
stream-json transcript is kept for every run, so failures can be explained and file accesses
outside the workspace (the repository, hidden tests, reference solutions) can be audited.
Writes ROOT/results.jsonl and prints a markdown table. Re-running with the same --root reuses
finished transcripts (and their workspaces) instead of paying for those runs again.

Isolation is not airtight: an agent allowed to run python can read any file the user can. The
audit reports every tool input that mentions the repository path or the hidden/solution
folders.
"""
import argparse
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from .common import HERE, REPO, TASKS, build_workspace
from .grade import grade

PROMPT = """You are working in the current directory, which contains everything you need.
Complete the task described below. Work only inside this directory. When you are done, reply
with a short summary of what you changed and how you checked it.

{readme}"""
ALLOWED = ["Read", "Edit", "Write", "Glob", "Grep", "Bash(python3:*)", "Bash(python:*)", "Bash(ls:*)"]
SUSPICIOUS = (REPO, "coding_agent/hidden", "coding_agent/solutions", "wrong_solutions", "rlgym/belief")


def audit(events: List[dict]) -> Dict[str, object]:
    """Tool calls made, and any whose input reaches outside the workspace."""
    tools: Dict[str, int] = {}
    outside: List[str] = []
    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tools[block["name"]] = tools.get(block["name"], 0) + 1
            text = json.dumps(block.get("input", {}))
            if any(s in text for s in SUSPICIOUS):
                outside.append(f"{block['name']}: {text[:200]}")
    return {"tool_calls": tools, "outside_workspace": outside}


def _events(text: str) -> List[dict]:
    events = []
    for line in text.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events


def run_one(task: str, run: int, root: str, budget: float, timeout: float) -> dict:
    """Run the agent once (or reuse a finished transcript from an earlier invocation) and grade it."""
    workspace = os.path.join(root, f"{task}_run{run}", "workspace")
    transcript = os.path.join(os.path.dirname(workspace), "transcript.jsonl")
    if os.path.exists(transcript):
        with open(transcript) as f:
            events = _events(f.read())
        if any(e.get("type") == "result" for e in events):
            final = next(e for e in reversed(events) if e.get("type") == "result")
            return _record(task, run, workspace, transcript, events, round(final.get("duration_ms", 0) / 1000, 1),
                           0, False, reused=True)
    shutil.rmtree(os.path.dirname(workspace), ignore_errors=True)
    build_workspace(task, workspace)
    with open(os.path.join(workspace, "README.md")) as f:
        prompt = PROMPT.format(readme=f.read())
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED, "--max-budget-usd", str(budget)]
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout)
        stdout, exit_code, timed_out = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        stdout, exit_code, timed_out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), None, True
    seconds = round(time.time() - started, 1)
    with open(transcript, "w") as f:
        f.write(stdout)
    return _record(task, run, workspace, transcript, _events(stdout), seconds, exit_code, timed_out)


def _record(task: str, run: int, workspace: str, transcript: str, events: List[dict], seconds: float,
            exit_code, timed_out: bool, reused: bool = False) -> dict:
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    init = next((e for e in events if e.get("type") == "system"), {})
    result = grade(task, workspace)
    return {"task": task, "run": run, "passed": result["passed"], "grade": result, "seconds": seconds,
            "exit_code": exit_code, "timed_out": timed_out, "model": init.get("model"),
            "cost_usd": final.get("total_cost_usd"), "turns": final.get("num_turns"),
            "agent_summary": (final.get("result") or "")[:1500], "audit": audit(events), "transcript": transcript,
            "reused_transcript": reused}


def table(rows: List[dict]) -> str:
    lines = ["| task | run | result | detail | turns | cost $ | minutes | outside-workspace accesses |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["task"], r["run"])):
        g = r["grade"]
        detail = (f"tampered {g['tampered']}" if g.get("tampered") else
                  f"{g.get('wrong')} / {g.get('states')} wrong" if "states" in g else
                  f"failed {g.get('failed_checks')} regressions {len(g.get('regressions', []))}" if "regressions" in g else
                  f"win rate {g.get('win_rate')} vs {g.get('threshold')}" if "win_rate" in g else g.get("reason", ""))
        lines.append(f"| {r['task']} | {r['run']} | {'PASS' if r['passed'] else 'FAIL'} | {detail} | {r['turns']} | "
                     f"{r['cost_usd']} | {r['seconds'] / 60:.1f} | {len(r['audit']['outside_workspace'])} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="out/agent_runs")
    ap.add_argument("--tasks", nargs="+", default=list(TASKS))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--budget-usd", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=1800)
    args = ap.parse_args()
    if shutil.which("claude") is None:
        ap.error("the `claude` CLI is not on PATH")
    os.makedirs(args.root, exist_ok=True)
    jobs = [(t, r) for r in range(1, args.runs + 1) for t in args.tasks]
    with ThreadPoolExecutor(args.parallel) as pool:
        rows = list(pool.map(lambda job: run_one(job[0], job[1], args.root, args.budget_usd, args.timeout), jobs))
    with open(os.path.join(args.root, "results.jsonl"), "w") as f:
        f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    print(table(rows))


if __name__ == "__main__":
    main()
