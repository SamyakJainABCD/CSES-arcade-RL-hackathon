"""Baseline bot: HeuristicPolicy with a next-shell estimator chosen by params["belief"].

"exact" (default) uses the generator-exact belief; "naive" uses live-left / shells-left.
Self-contained so it runs in the sandbox, which only provides schemas.py and wire.py.
"""
import belief
import policy


class Bot:
    def init(self, params=None):
        params = params or {}
        estimator = belief.p_next_live_naive if params.get("belief") == "naive" else belief.p_next_live
        self.policy = policy.HeuristicPolicy(estimator)

    def play(self, obs):
        return self.policy.play(obs)

    def pick_upgrade(self, obs):
        return self.policy.pick(obs)
