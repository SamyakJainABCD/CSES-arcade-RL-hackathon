"""LLM player: reply parsing, fallbacks, and the offline mock provider."""
import os
import unittest

import game_API as api
from rlgym.loader import LoadedBot
from schemas import ActionType

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM = os.path.join(ROOT, "agents", "llm_bot")


def bot_with_reply(reply: str) -> LoadedBot:
    bot = LoadedBot(LLM, params={"provider": "mock"})
    bot.bot.call = lambda system, user, model: (reply, {"input_tokens": 1, "output_tokens": 1})
    return bot


class LLMBotTest(unittest.TestCase):
    def setUp(self):
        self.obs = api.play_observation(api.initGame(0, 2))

    def test_parses_json_inside_prose(self):
        action = bot_with_reply('Sure. {"action": 1} is best.').play(self.obs)
        self.assertEqual((action.action, action.target), (ActionType.SHOOT, 1))

    def test_unparseable_reply_falls_back_to_shooting_an_opponent(self):
        for reply in ("no idea", '{"action": "one"}', '{"action": 99}', '{"action": true}', '{"action": 2}'):
            bot = bot_with_reply(reply)
            action = bot.play(self.obs)
            self.assertEqual((action.action, action.target), (ActionType.SHOOT, 1), reply)
            self.assertEqual(bot.bot.stats["parse_failures"], 1, reply)

    def test_off_list_action_is_passed_through(self):
        bot = bot_with_reply('{"action": 4}')  # juice, which this player does not hold
        self.assertEqual(bot.play(self.obs).useUpgrade.value, "JUICE")
        self.assertEqual(bot.bot.stats["off_list"], 1)

    def test_mock_provider_only_chooses_listed_actions(self):
        from rlgym.llm_eval import run
        import tempfile
        result = run("mock", None, 3, os.path.join(ROOT, "bots", "greedy_bot"), tempfile.mkdtemp())
        self.assertEqual(result["parse_failure_rate"], 0.0)
        self.assertEqual(result["illegal_action_rate"], 0.0)
        self.assertEqual(result["matches"], 6)


if __name__ == "__main__":
    unittest.main()
