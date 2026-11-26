"""BuckshotEnv smoke tests and reward properties."""
import os
import random
import unittest

from rlgym.env import OBS_SIZE, BuckshotEnv
from rlgym.rewards import NaiveDamageReward, PlacementReward, PotentialShapedReward

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GREEDY = os.path.join(ROOT, "bots", "greedy_bot")
RANDOM = os.path.join(ROOT, "bots", "random_bot")


def run_episode(env, seed, rng, illegal_every=0):
    obs, info = env.reset(seed=seed)
    total, steps = 0.0, 0
    while True:
        legal = [i for i, ok in enumerate(info["action_mask"]) if ok]
        action = rng.choice(legal)
        if illegal_every and steps % illegal_every == illegal_every - 1:
            action = next(i for i, ok in enumerate(info["action_mask"]) if not ok)
        obs, reward, terminated, truncated, info = env.step(action)
        assert len(obs) == OBS_SIZE
        total += reward
        steps += 1
        if terminated or truncated:
            return total, info


class EnvSmokeTest(unittest.TestCase):
    def test_episodes_finish_with_placement_return(self):
        rng = random.Random(0)
        for k in (2, 3, 4):
            for seat in range(k):
                env = BuckshotEnv([GREEDY] * (k - 1), num_players=k, agent_seat=seat)
                for seed in range(5):
                    total, info = run_episode(env, seed, rng)
                    expected = (k - 1) - 2 * (info["placement"] - 1)
                    self.assertEqual(total, expected)

    def test_shaped_return_equals_placement_return(self):
        """gamma = 1 and phi(terminal) = 0: shaping telescopes away, so returns match exactly."""
        for seed in range(10):
            plain = run_episode(BuckshotEnv([RANDOM], reward=PlacementReward()), seed, random.Random(seed))[0]
            shaped = run_episode(BuckshotEnv([RANDOM], reward=PotentialShapedReward()), seed, random.Random(seed))[0]
            self.assertAlmostEqual(plain, shaped)

    def test_illegal_actions_strike_then_eliminate(self):
        env = BuckshotEnv([RANDOM], num_players=2)
        _, info = run_episode(env, 3, random.Random(0), illegal_every=1)
        self.assertTrue(info["illegal_action"])
        self.assertEqual(env.faults[0], 2)
        self.assertEqual(info["placement"], 2)

    def test_same_seed_same_episode(self):
        a = run_episode(BuckshotEnv([GREEDY, GREEDY], 3, reward=NaiveDamageReward()), 11, random.Random(5))
        b = run_episode(BuckshotEnv([GREEDY, GREEDY], 3, reward=NaiveDamageReward()), 11, random.Random(5))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
