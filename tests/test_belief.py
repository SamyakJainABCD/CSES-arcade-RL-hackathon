"""Belief exactness against brute-force enumeration of the engine's shell generator."""
import itertools
import random
import unittest
from fractions import Fraction

import game_API as api
import wire
from rlgym.belief import p_next_live, p_next_live_naive, prefix_distribution
from schemas import Stage
from rlgym.actions import random_legal


def generator_sequences(lives: int, blanks: int):
    """Every gun _setup_round can produce for these counts, with its exact probability."""
    def rec(prefix, l, b, p):
        if l == 0 and b == 0:
            yield tuple(prefix), p
            return
        branches = [(True, l - 1, b), (False, l, b - 1)] if l and b else [(l > 0, l - (l > 0), b - (l == 0))]
        share = p / len(branches)
        for shell, nl, nb in branches:
            yield from rec(prefix + [shell], nl, nb, share)
    yield from rec([], lives, blanks, Fraction(1))


def brute_force(lives, blanks, n, known_lives, known_blanks, unknown):
    """P(shell n is live | the known part of the prefix), unknown positions uniform in the prefix."""
    num = den = Fraction(0)
    for seq, p in generator_sequences(lives, blanks):
        for hidden in itertools.combinations(range(n), unknown):
            known = [seq[i] for i in range(n) if i not in hidden]
            if sum(known) == known_lives and len(known) - sum(known) == known_blanks:
                den += p
                num += p * seq[n]
    return None if den == 0 else num / den


def make_obs(lives, blanks, remaining, lives_shot, blanks_shot, lives_ej, blanks_ej, unknown, nxt="UNKNOWN"):
    return {"lives_init": lives, "blanks_init": blanks, "rounds_remaining": remaining,
            "lives_shot": lives_shot, "blanks_shot": blanks_shot, "next_round": nxt,
            "ejections": {"lives_ejected": lives_ej, "blanks_ejected": blanks_ej, "unknowns_ejected": unknown}}


class BeliefExactnessTest(unittest.TestCase):
    def test_matches_enumeration_on_small_guns(self):
        checked = 0
        for lives in range(0, 5):
            for blanks in range(0, 5):
                total = lives + blanks
                for n in range(total):
                    for unknown in range(0, min(n, 3) + 1):
                        for known_lives in range(0, n - unknown + 1):
                            known_blanks = n - unknown - known_lives
                            expected = brute_force(lives, blanks, n, known_lives, known_blanks, unknown)
                            if expected is None:
                                continue
                            obs = make_obs(lives, blanks, total - n, known_lives, known_blanks, 0, 0, unknown)
                            self.assertAlmostEqual(p_next_live(obs), float(expected), places=12,
                                                   msg=(lives, blanks, n, known_lives, unknown))
                            checked += 1
        self.assertGreater(checked, 300)

    def test_prefix_distribution_sums_to_one(self):
        for lives, blanks, n in ((3, 5, 4), (6, 2, 7), (1, 1, 1)):
            self.assertAlmostEqual(sum(prefix_distribution(lives, blanks, n)), 1.0)

    def test_naive_differs_when_both_kinds_remain(self):
        obs = make_obs(6, 2, 8, 0, 0, 0, 0, 0)
        self.assertEqual(p_next_live(obs), 0.5)
        self.assertEqual(p_next_live_naive(obs), 0.75)

    def test_mag_glass_reveal_is_certain(self):
        self.assertEqual(p_next_live(make_obs(1, 7, 8, 0, 0, 0, 0, 0, "LIVE")), 1.0)
        self.assertEqual(p_next_live(make_obs(7, 1, 8, 0, 0, 0, 0, 0, "BLANK")), 0.0)

    def test_accepts_objects_and_wire_dicts_from_real_games(self):
        rng = random.Random(0)
        for seed in range(20):
            state = api.initGame(seed, 3)
            while not state.game_over:
                if state.stage == Stage.PLAY:
                    obs = api.play_observation(state)
                    self.assertEqual(p_next_live(obs), p_next_live(wire.to_wire(obs)))
                    self.assertTrue(0.0 <= p_next_live(obs) <= 1.0)
                    api.step_PLAY(state, random_legal(obs, rng))
                else:
                    api.step_PICK_UPGRADE(state, random_legal(api.upgrade_observation(state), rng))


class _ScriptedRng:
    """Stands in for state.rng: a fixed live count, then coin flips taken from `bits`."""

    def __init__(self, live_count, bits):
        self.live_count, self.bits = live_count, list(bits)

    def randint(self, lo, hi):
        return self.live_count

    def randrange(self, n):
        return self.bits.pop(0)


class GeneratorModelTest(unittest.TestCase):
    def test_enumerator_reproduces_setup_round(self):
        """Feed _setup_round every bit string; the induced distribution must equal generator_sequences."""
        state = api.initGame(0, 2)  # 2 players, session 0 -> 4 shells, 1..3 live
        for lives in (1, 2, 3):
            seen = {}
            for bits in itertools.product((0, 1), repeat=4):
                state.rng = _ScriptedRng(lives, bits)
                api._setup_round(state)
                used = 4 - len(state.rng.bits)
                key = tuple(state.round_contents)
                # each distinct outcome consumes `used` flips: probability 2**-used, counted once
                seen[key] = Fraction(1, 2 ** used)
            self.assertEqual(seen, dict(generator_sequences(lives, 4 - lives)))


if __name__ == "__main__":
    unittest.main()
