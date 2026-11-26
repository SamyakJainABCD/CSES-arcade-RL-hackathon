# Task T1: next-shell probability

This workspace holds a Buckshot Roulette engine (`game_API.py`, `schemas.py`, `wire.py`).

Implement `p_next_live(obs)` in `belief.py`. `obs` is a PLAY-stage observation in wire form, a
plain dict like the one `wire.to_wire(game_API.play_observation(state))` returns. The function
must return the exact probability that the next shell in the gun is live. Use only what that
player can see, and assume the gun was loaded by the shell generator exactly as `game_API.py`
implements it.

Grading
- Hidden states are sampled from real games. In every state no other player has ejected a shell
  this player did not see (`ejections.unknowns_ejected == 0`).
- Each answer must be within 1e-9 of the exact value.
- Do not edit `game_API.py`, `schemas.py`, `wire.py` or this README. The grader checks their
  sha256 and uses its own copy of the engine.
- Standard library only. `belief.py` is imported in a fresh interpreter with this directory on
  `sys.path`.
