"""The verifier's checks pass on the engine and catch planted faults."""
import random
import unittest
from collections import Counter

import game_API as api
from rlgym import verify
from rlgym.actions import action_mask, decode, encode, stage_indices
from schemas import Stage


class VerifierTest(unittest.TestCase):
    def test_random_games_have_no_violations(self):
        for k in (2, 3, 4):
            for seed in range(5):
                bias = {"naive": [], "exact": [], "outcome": []}
                self.assertEqual(verify.play_game(seed, k, 1, Counter(), bias), [])

    def test_mask_check_catches_a_wrong_mask(self):
        state = api.initGame(0, 2)
        obs = verify.observe(state)
        obs.players[1].health = 0  # the mask now forbids shooting seat 1, but the engine allows it
        self.assertTrue(any("mask says False, engine says True" in e for e in verify.check_mask(state, obs)))

    def test_invariants_catch_a_dead_player_on_turn(self):
        state = api.initGame(0, 3)
        state.players[0].health = 0
        state.alive_players, state.elimination_order = 2, [0]
        self.assertIn("turn 0 belongs to a dead player", verify.check_invariants(state))

    def test_encode_inverts_decode_on_legal_actions(self):
        rng = random.Random(1)
        state = api.initGame(4, 4)
        while not state.game_over:
            obs = verify.observe(state)
            mask = action_mask(obs)
            for index in stage_indices(obs):
                if mask[index]:
                    self.assertEqual(encode(decode(index, obs), obs), index)
            legal = [i for i in stage_indices(obs) if mask[i]]
            verify.apply(state, decode(rng.choice(legal), obs))

    def test_decode_rejects_seats_past_the_table(self):
        obs = api.play_observation(api.initGame(0, 2))
        with self.assertRaises(ValueError):
            decode(2, obs)


if __name__ == "__main__":
    unittest.main()
