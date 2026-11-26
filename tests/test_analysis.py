"""Blunder classification on hand-built decisions and on real rollout output."""
import json
import os
import tempfile
import unittest

from rlgym.analysis import analyze, classify
from rlgym.rollout import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def decision(next_round="UNKNOWN", action="SHOOT", target=0, upgrade=None, health=5, lives_left=2, blanks_left=2):
    player = {"health": health, "has_pool_floatie_on": False,
              "upgrades": {"juice": 1, "coffee": 0, "mag_glass": 1, "pool_floatie": 0, "hand_saw": 0}}
    obs = {"max_health": 5, "players": [player, dict(player)], "turn": 0, "session_no": 0,
           "lives_init": lives_left, "blanks_init": blanks_left, "rounds_remaining": lives_left + blanks_left,
           "lives_shot": 0, "blanks_shot": 0, "next_round": next_round,
           "ejections": {"lives_ejected": 0, "blanks_ejected": 0, "unknowns_ejected": 0}}
    return {"seat": 0, "stage": "PLAY", "obs": obs, "action": {"action": action, "useUpgrade": upgrade, "target": target}}


class ClassifyTest(unittest.TestCase):
    def test_self_shot_on_known_live(self):
        c = classify(decision(next_round="LIVE", target=0))
        self.assertTrue(c["self_known_live"] and c["self_certain_live"] and c["against_belief"])

    def test_opponent_shot_on_certain_blank(self):
        c = classify(decision(target=1, lives_left=0, blanks_left=3))
        self.assertTrue(c["opp_certain_blank"] and not c["opp_known_blank"])

    def test_coin_flip_self_shot_and_wasted_upgrades(self):
        self.assertTrue(classify(decision(target=0))["self_at_coin_flip"])
        self.assertTrue(classify(decision("BLANK", "USE_UPGRADE", None, "MAG_GLASS"))["redundant_mag_glass"])
        self.assertTrue(classify(decision(action="USE_UPGRADE", target=None, upgrade="JUICE"))["juice_full_health"])

    def test_reads_rollout_trajectories(self):
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        evaluate([os.path.join(ROOT, "bots", n) for n in ("greedy_bot", "belief_bot")], 3, trajectories=path)
        report = analyze([path])
        self.assertEqual(set(report), {"greedy_bot", "belief_bot"})
        self.assertEqual(report["belief_bot"]["self_at_coin_flip"]["count"], 0)
        with open(path) as f:
            self.assertTrue(any("summary" in json.loads(line) for line in f))


if __name__ == "__main__":
    unittest.main()
