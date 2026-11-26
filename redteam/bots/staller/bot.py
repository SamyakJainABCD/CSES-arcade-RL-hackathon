"""Red team: belief_bot's policy, but when ahead on health it burns actions to run out the clock.

At the 300-action cap the engine ranks survivors by health. So a bot that is ahead can spend
its turn on pointless juice and magnifying-glass uses instead of risking a shot.
"""
import belief
import policy
from schemas import *


class Bot:
    def init(self, params=None):
        self.policy = policy.HeuristicPolicy(belief.p_next_live)

    def play(self, obs):
        me, players = obs.turn, obs.players
        mine = players[me].upgrades
        lead = players[me].health - max(p.health for i, p in enumerate(players) if i != me and p.health > 0)
        if lead > 0:
            action = Action_PLAY()
            action.action, action.target = ActionType.USE_UPGRADE, None
            if mine.juice > 0:
                action.useUpgrade = UpgradeType.JUICE
                return action
            if mine.mag_glass > 0 and obs.rounds_remaining > 0:
                action.useUpgrade = UpgradeType.MAG_GLASS
                return action
        return self.policy.play(obs)

    def pick_upgrade(self, obs):
        return self.policy.pick(obs)
