# Coding-agent benchmark results

Agent: Claude Code headless (`claude -p`), model `claude-opus-5-5`, run by
`python -m benchmarks.coding_agent.run_agents`. Each run used a fresh workspace, auto-accepted
edits, Bash limited to `python`/`ls`, and a $5 budget cap. Grades come from
`python -m benchmarks.coding_agent.grade`, re-run serially on each saved workspace after the
agents finished.

**Coverage: T1 and T2 have 3 runs each. T3 was not run.** Two earlier batches were lost: a
runner bug crashed one before grading, and a machine reboot wiped the other's transcripts. In the
last batch, both T3 runs were stopped part-way, and the remaining agent runs were then cancelled
to save usage. To finish, run:

```
python -m benchmarks.coding_agent.run_agents --root ~/.cache/cses-agent-runs --tasks T3 --runs 3
```

The runner reuses finished transcripts, so only the missing runs cost anything. A single T3 run
in the lost batch cost about $1.90 and took 39 turns.

| task | run | result | grader detail | turns | cost $ | minutes | reads outside workspace |
|---|---|---|---|---|---|---|---|
| T1 | 1 | PASS | 0 / 3000 states wrong | 8 | 0.387 | 2.3 | 0 |
| T1 | 2 | PASS | 0 / 3000 states wrong | 6 | 0.349 | 0.9 | 0 |
| T1 | 3 | PASS | 0 / 3000 states wrong | 8 | 0.417 | 1.0 | 0 |
| T2 | 1 | FAIL | failed `direct target=True`; 0 / 18 log regressions | 7 | 0.229 | 0.5 | 0 |
| T2 | 2 | PASS | all checks; 0 / 18 log regressions | 10 | 0.265 | 0.6 | 0 |
| T2 | 3 | PASS | all checks; 0 / 18 log regressions | 8 | 0.246 | 0.5 | 0 |
| T3 | - | not run | - | - | - | - | - |

**Pass rates:** T1 3/3, T2 2/3, T3 not measured. The total for the six graded runs was $1.89.

## How the runs went

**T1 (next-shell probability).** All three runs read `_setup_round` and saw that the gun is
filled by coin flips, not shuffled. All three returned 0.5 whenever both kinds remain, and checked
it against their own brute-force enumeration before finishing. None fell for the plausible
answer (live-left / shells-left), which the grader rejects on 1581 of the 3000 hidden states
(`wrong_solutions/T1_naive`).

**T2 (floatie bug).** Every run added a bounds check before the list index and caused no
regressions: full match logs on 18 fixed seeds hash the same as the original engine. Run 1
guarded with `isinstance(target, int)`. In Python `bool` is a subclass of `int`, so
`target=True` still put a floatie on player 1 and the hidden check failed. Runs 2 and 3 excluded
`bool` explicitly. No run made the classic mistake the grader is built to catch: checking only
`target >= len(players)`, which leaves `-1` working (`wrong_solutions/T2_upper_bound_only` fails
on -1, -5 and True).

The task README says "any pool floatie target that is not a valid player index" and does not
mention booleans. In real tournaments `wire.action_play_from_wire` already rejects boolean
targets as `invalid`, so run 1's fix would be safe there. This hidden check is stricter than the
README's explicit wording. If the benchmark is reused, the README should name booleans.

**Isolation audit.** The runner scanned every tool call for paths into the repository, `hidden/`,
`solutions/` or `rlgym/belief`. No run touched any of them. This is an audit, not a sandbox: an
agent allowed to run Python can read any file the user can.

## Grader controls

`python -m unittest tests.test_benchmark` (passes):

- the reference solutions pass all three tasks;
- the plausible wrong solutions (`T1_naive`, `T2_upper_bound_only`, `T3_greedy`) fail;
- an edit to a protected engine file is caught by the sha256 check.

T3 threshold: belief_bot (the reference) won 69.0% (138/200) through the engine on calibration
seeds (`grade --task T3 --calibrate`). The threshold is 0.60, two standard errors below that at
the hidden sample size of 120 matches. On the hidden seeds the reference scored 0.717 and
greedy_bot scored 0.500.
