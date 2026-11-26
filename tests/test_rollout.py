"""In-process rollouts must reproduce the out-of-process engine exactly for well-behaved bots."""
import os
import unittest

from engine.run_match import Submission, run_match
from rlgym.loader import LoadedBot
from rlgym.rollout import play_match
from rlgym.stats import wilson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOTS = [os.path.join(ROOT, "bots", n) for n in ("belief_bot", "greedy_bot", "random_bot", "belief_bot")]


class RolloutMatchesEngineTest(unittest.TestCase):
    def test_same_outcome_as_run_match(self):
        for k in (2, 4):
            for seed in range(3):
                paths = BOTS[:k]
                engine = run_match([Submission(f"b{i}", p) for i, p in enumerate(paths)], seed, backend="local")
                local = play_match([LoadedBot(p) for p in paths], [f"b{i}" for i in range(k)], seed)
                for key in ("placements", "actions", "final_health", "reason", "faults"):
                    self.assertEqual(engine[key], local[key], (k, seed, key))

    def test_wilson_interval(self):
        low, high = wilson(285, 400)
        self.assertAlmostEqual(low, 0.6663, places=3)
        self.assertAlmostEqual(high, 0.7547, places=3)
        self.assertEqual(wilson(0, 0), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
