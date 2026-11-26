# Task T3: beat greedy_bot

Write a Buckshot Roulette bot in `my_bot/` that beats `opponents/greedy_bot` head to head.

- The interface is in the repository README section "Get Started": `my_bot/bot.py` defines
  `class Bot` with `play(obs)` and `pick_upgrade(obs)`. Files next to `bot.py` are importable.
- The bot runs in a separate process through `engine.run_match` (local backend here, Docker in
  production): standard library plus `schemas.py`/`wire.py` only, 50 ms per decision, 0.5 s per
  match, 5 MB submission.
- Grading plays 2-player matches against greedy_bot on hidden seeds, both seatings per seed.
  You pass if your win rate reaches the hidden threshold. It is well above 50% but has been
  shown to be reachable.
- Do not edit anything outside `my_bot/`. The grader checks sha256 and uses its own engine and
  its own greedy_bot.

Try it: `python -m engine.tournament my_bot opponents/greedy_bot --backend local --group-size 2 --seeds 20`
