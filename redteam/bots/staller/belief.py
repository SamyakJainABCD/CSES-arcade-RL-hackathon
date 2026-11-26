"""Probability that the next shell is live, from a PLAY observation (object or wire dict).

`_setup_round` does not shuffle the gun. While both kinds remain it flips a fair coin for each
position, and once one kind runs out the rest is forced. So the next shell depends only on how many
of each kind are left: if both remain, it is live with probability exactly 1/2.

`p_next_live_naive` is the answer for a uniformly shuffled gun (live left / shells left). It is the
obvious estimate and the wrong one for this engine.

Shells that other players ejected with coffee are unknown to us. `p_next_live` sums over how many
lives the consumed prefix holds, weighting each count k by
    P_generator(k lives in the first n shells) * P_hypergeometric(our known shells | k).
This is exact if the unknown shells sit at uniformly random positions in the prefix,
independent of their contents. The observation records no order, so we assume that.
"""
from functools import lru_cache
from math import comb
from typing import Any, List, Tuple


def _get(obs: Any, name: str) -> Any:
    return obs[name] if isinstance(obs, dict) else getattr(obs, name)


def _counts(obs: Any) -> Tuple[int, int, int, int, int, int, str]:
    """(lives_init, blanks_init, rounds_remaining, known lives used, known blanks used, unknowns, next)."""
    ej = _get(obs, "ejections")
    nxt = _get(obs, "next_round")
    return (_get(obs, "lives_init"), _get(obs, "blanks_init"), _get(obs, "rounds_remaining"),
            _get(obs, "lives_shot") + _get(ej, "lives_ejected"),
            _get(obs, "blanks_shot") + _get(ej, "blanks_ejected"),
            _get(ej, "unknowns_ejected"), getattr(nxt, "value", nxt))


def _next_given_left(lives_left: int, blanks_left: int) -> float:
    """The generator's next draw, given what is really left in the gun."""
    if lives_left > 0 and blanks_left > 0:
        return 0.5
    return 1.0 if lives_left > 0 else 0.0


@lru_cache(maxsize=4096)
def prefix_distribution(lives: int, blanks: int, n: int) -> Tuple[float, ...]:
    """P(the first n shells contain exactly k lives) under the coin-flip generator, for k = 0..n."""
    dist = {0: 1.0}  # lives drawn so far -> probability
    for drawn in range(n):
        nxt: dict = {}
        for k, p in dist.items():
            lives_left, blanks_left = lives - k, blanks - (drawn - k)
            p_live = _next_given_left(lives_left, blanks_left)
            if p_live > 0:
                nxt[k + 1] = nxt.get(k + 1, 0.0) + p * p_live
            if p_live < 1:
                nxt[k] = nxt.get(k, 0.0) + p * (1 - p_live)
        dist = nxt
    return tuple(dist.get(k, 0.0) for k in range(n + 1))


def p_next_live_naive(obs: Any) -> float:
    """Live shells left / shells left, as if the gun were uniformly shuffled."""
    lives, blanks, remaining, known_lives, _, unknown, nxt = _counts(obs)
    if nxt in ("LIVE", "BLANK"):
        return 1.0 if nxt == "LIVE" else 0.0
    if remaining <= 0:
        return 0.0
    return (lives - known_lives) / (remaining + unknown)


def p_next_live(obs: Any) -> float:
    """Exact P(next shell is live) for the engine's generator (see module docstring)."""
    lives, blanks, remaining, known_lives, known_blanks, unknown, nxt = _counts(obs)
    if nxt in ("LIVE", "BLANK"):
        return 1.0 if nxt == "LIVE" else 0.0
    if remaining <= 0:
        return 0.0
    if unknown == 0:
        return _next_given_left(lives - known_lives, blanks - known_blanks)
    n = lives + blanks - remaining
    prefix = prefix_distribution(lives, blanks, n)
    total = weighted = 0.0
    for k in range(known_lives, known_lives + unknown + 1):
        if k > lives or n - k > blanks:
            continue
        w = prefix[k] * comb(k, known_lives) * comb(n - k, known_blanks)
        total += w
        weighted += w * _next_given_left(lives - k, blanks - (n - k))
    return weighted / total if total else p_next_live_naive(obs)


def lives_left_distribution(obs: Any) -> List[float]:
    """P(exactly j live shells remain), j = 0..rounds_remaining. Useful as a model feature."""
    lives, blanks, remaining, known_lives, known_blanks, unknown, _ = _counts(obs)
    n = lives + blanks - remaining
    out = [0.0] * (remaining + 1)
    if unknown == 0:
        j = lives - known_lives
        if 0 <= j <= remaining:
            out[j] = 1.0
        return out
    prefix = prefix_distribution(lives, blanks, n)
    for k in range(known_lives, known_lives + unknown + 1):
        j = lives - k
        if 0 <= j <= remaining and n - k <= blanks:
            out[j] += prefix[k] * comb(k, known_lives) * comb(n - k, known_blanks)
    total = sum(out)
    return [p / total for p in out] if total else out
