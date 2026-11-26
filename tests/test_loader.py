"""In-process loader: bots shipping same-named helper modules must not see each other's."""
import filecmp
import os
import sys
import tempfile
import unittest

import game_API as api
from rlgym.belief import p_next_live
from rlgym.loader import LoadedBot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOT = """
import policy

class Bot:
    def init(self, params=None):
        self.params = params

    def play(self, obs):
        import late  # imported lazily, during a decision
        return (policy.VALUE, late.VALUE)

    def pick_upgrade(self, obs):
        return policy.VALUE
"""


def make_bot(value: str) -> str:
    path = tempfile.mkdtemp(prefix="loaderbot_")
    for name, source in (("bot.py", BOT), ("policy.py", f"VALUE = {value!r}\n"), ("late.py", f"VALUE = {value!r}\n")):
        with open(os.path.join(path, name), "w") as f:
            f.write(source)
    return path


class LoaderIsolationTest(unittest.TestCase):
    def test_same_named_helpers_stay_private(self):
        a, b = LoadedBot(make_bot("A")), LoadedBot(make_bot("B"))
        for _ in range(2):
            self.assertEqual(a.play(None), ("A", "A"))
            self.assertEqual(b.play(None), ("B", "B"))
            self.assertEqual(a.pick_upgrade(None), "A")
        self.assertNotIn("policy", sys.modules)
        self.assertNotIn("late", sys.modules)

    def test_outside_module_with_same_name_is_untouched(self):
        sentinel = type(sys)("policy")
        sys.modules["policy"] = sentinel
        try:
            bot = LoadedBot(make_bot("C"))
            self.assertEqual(bot.play(None), ("C", "C"))
            self.assertIs(sys.modules["policy"], sentinel)
        finally:
            del sys.modules["policy"]

    def test_params_json_is_passed_to_init(self):
        bot = LoadedBot(os.path.join(ROOT, "bots", "greedy_bot"))
        self.assertEqual(bot.params, {"belief": "naive"})


class BaselineBotsTest(unittest.TestCase):
    def test_baselines_share_code_and_differ_only_in_params(self):
        greedy, belief = (os.path.join(ROOT, "bots", n) for n in ("greedy_bot", "belief_bot"))
        for name in ("bot.py", "policy.py", "belief.py"):
            self.assertTrue(filecmp.cmp(os.path.join(greedy, name), os.path.join(belief, name), shallow=False))
        self.assertTrue(filecmp.cmp(os.path.join(belief, "belief.py"), os.path.join(ROOT, "rlgym", "belief.py"),
                                    shallow=False), "bots/*/belief.py must be a copy of rlgym/belief.py")

    def test_estimators_differ_where_expected(self):
        obs = api.play_observation(api.initGame(1, 2))
        greedy = LoadedBot(os.path.join(ROOT, "bots", "greedy_bot"))
        belief = LoadedBot(os.path.join(ROOT, "bots", "belief_bot"))
        self.assertEqual(belief.bot.policy.p_live(obs), p_next_live(obs))
        self.assertNotEqual(greedy.bot.policy.p_live.__name__, belief.bot.policy.p_live.__name__)


if __name__ == "__main__":
    unittest.main()
