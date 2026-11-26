"""Regression tests for engine bugs found while building the verifier."""
import os
import random
import unittest
from unittest import mock

import game_API as api
from engine.run_match import Submission, run_match
from schemas import *

from rlgym.actions import random_legal
from tests.helpers import play_action, snapshot, write_bot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANDOM_BOT = os.path.join(ROOT, "bots", "random_bot")

FLOATIE_99_BOT = """
from schemas import *

class Bot:
    def play(self, obs):
        action = Action_PLAY()
        action.useUpgrade = None
        if obs.players[obs.turn].upgrades.pool_floatie > 0:
            action.action, action.useUpgrade, action.target = ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, 99
        else:
            action.action = ActionType.SHOOT
            action.target = next(i for i, p in enumerate(obs.players) if i != obs.turn and p.health > 0)
        return action

    def pick_upgrade(self, obs):
        action = Action_PICK_UPGRADES()
        for upgrade, name in ((UpgradeType.POOL_FLOATIE, "pool_floatie"), (UpgradeType.JUICE, "juice"),
                              (UpgradeType.COFFEE, "coffee"), (UpgradeType.MAG_GLASS, "mag_glass"),
                              (UpgradeType.HAND_SAW, "hand_saw")):
            if getattr(obs.available_upgrades, name) > 0:
                action.chosen_upgrade = upgrade
                return action
"""


class FloatieTargetTest(unittest.TestCase):
    def setUp(self):
        self.state = api.initGame(7, 3)
        self.state.players[0].upgrades.pool_floatie = 1

    def assert_rejected(self, target):
        before = snapshot(self.state)
        with self.assertRaises(ValueError):
            api.step_PLAY(self.state, play_action(ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, target))
        self.assertEqual(snapshot(self.state), before)

    def test_target_past_end_is_illegal(self):
        self.assert_rejected(99)

    def test_negative_target_is_illegal(self):
        self.assert_rejected(-1)
        self.assert_rejected(-5)

    def test_bool_and_str_targets_are_illegal(self):
        self.assert_rejected(True)
        self.assert_rejected("1")

    def test_valid_target_still_works(self):
        api.step_PLAY(self.state, play_action(ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, 2))
        self.assertTrue(self.state.players[2].has_pool_floatie_on)
        self.assertEqual(self.state.players[0].upgrades.pool_floatie, 0)


class RunMatchSurvivesBadTargetsTest(unittest.TestCase):
    def test_floatie_99_is_an_illegal_fault_not_a_crash(self):
        bot = write_bot(FLOATIE_99_BOT)
        seats = [Submission("floatie99", bot), Submission("random", RANDOM_BOT)]
        faulted = False
        for seed in range(10):
            summary = run_match(seats, seed, backend="local")
            if summary["faults"][0]:
                self.assertEqual(set(summary["faults"][0]), {"illegal"})
                faulted = True
        self.assertTrue(faulted, "the bot never held a floatie; pick seeds that reach session 2")

    def test_unexpected_engine_exception_becomes_illegal_fault(self):
        real_step = api.step_PLAY

        def flaky_step(state, action):
            if action.action == ActionType.USE_UPGRADE and action.useUpgrade == UpgradeType.MAG_GLASS:
                raise KeyError("boom")
            return real_step(state, action)

        seats = [Submission("random", RANDOM_BOT, {"seed": 1}), Submission("random2", RANDOM_BOT, {"seed": 2})]
        with mock.patch.object(api, "step_PLAY", flaky_step):
            summaries = [run_match(seats, seed, backend="local") for seed in range(5)]
        kinds = {kind for s in summaries for seat_faults in s["faults"] for kind in seat_faults}
        self.assertEqual(kinds, {"illegal"})


class TurnAfterSuicideTest(unittest.TestCase):
    """The shooter dies while every other living player has a floatie pending."""

    def setUp(self):
        self.state = api.initGame(3, 3)
        for seat in (1, 2):
            self.state.players[seat].has_pool_floatie_on = True

    def test_turn_never_lands_on_a_dead_player(self):
        self.state.players[0].health = 1
        self.state.round_contents[len(self.state.round_contents) - self.state.rounds_remaining] = True
        api.step_PLAY(self.state, play_action(ActionType.SHOOT, target=0))
        self.assertFalse(self.state.game_over)
        self.assertEqual(self.state.turn, 1)
        self.assertGreater(self.state.players[self.state.turn].health, 0)

    def test_living_shooter_still_goes_again(self):
        self.state.round_contents[len(self.state.round_contents) - self.state.rounds_remaining] = True
        self.state.rounds_remaining = max(self.state.rounds_remaining, 2)
        api.step_PLAY(self.state, play_action(ActionType.SHOOT, target=1))
        self.assertEqual(self.state.turn, 0)
        self.assertFalse(any(p.has_pool_floatie_on for p in self.state.players))

    def test_seed_30_random_legal_play(self):
        """Found by search: 65 of 5000 seeds reached a dead player's turn before the fix."""
        state, rng = api.initGame(30, 3), random.Random(30)
        for _ in range(300):
            if state.game_over:
                break
            self.assertGreater(state.players[state.turn].health, 0)
            obs = api.play_observation(state) if state.stage == Stage.PLAY else api.upgrade_observation(state)
            (api.step_PLAY if state.stage == Stage.PLAY else api.step_PICK_UPGRADE)(state, random_legal(obs, rng))


if __name__ == "__main__":
    unittest.main()
