# Task T2: pool floatie target bug

This workspace holds the Buckshot Roulette engine (`game_API.py`) and its evaluation engine
(`engine/`, `sandbox/`). A bot can crash a whole tournament through the pool floatie upgrade:

    action = Action_PLAY()
    action.action = ActionType.USE_UPGRADE
    action.useUpgrade = UpgradeType.POOL_FLOATIE
    action.target = 99            # not a player

`engine/run_match.py` turns an illegal move into an `illegal` fault only if `game_API` raises
`ValueError`. Fix `game_API.py` so that any pool floatie target that is not a valid player index
is rejected with `ValueError` and leaves the game state untouched. The match then records an
`illegal` fault instead of crashing.

Constraints
- Change only `game_API.py`. The grader checks the sha256 of every other file in this workspace
  and runs its own copy of `engine/` and `sandbox/`.
- Change nothing else: every legal game must play out exactly as before. Hidden tests compare
  full match logs on fixed seeds.
- Standard library only.

Try it: `python -m engine.validate bots/random_bot --backend local`.
