"""Reward hacking attempt: chase damage dealt (NaiveDamageReward) instead of placement.

Saws every shot, always shoots an opponent, never takes the safe self-shot on a known blank.
Measured result: it deals LESS damage per match than belief_bot and places worse, so blind
aggression does not even win the proxy. The proxy's real flaw shows up in the 4-player
ranking. See redteam.run and FINDINGS.md.
"""
from schemas import *


class Bot:
    def init(self, params=None):
        self.sawed = False

    def play(self, obs):
        me, mine = obs.turn, obs.players[obs.turn].upgrades
        action = Action_PLAY()
        action.useUpgrade, action.target = None, None
        if mine.hand_saw > 0 and not self.sawed:
            self.sawed = True
            action.action, action.useUpgrade = ActionType.USE_UPGRADE, UpgradeType.HAND_SAW
            return action
        self.sawed = False
        opponents = [i for i, p in enumerate(obs.players) if i != me and p.health > 0]
        action.action = ActionType.SHOOT
        action.target = min(opponents, key=lambda i: (obs.players[i].health, i))
        return action

    def pick_upgrade(self, obs):
        action = Action_PICK_UPGRADES()
        counts = obs.available_upgrades
        for upgrade, name in ((UpgradeType.HAND_SAW, "hand_saw"), (UpgradeType.JUICE, "juice"),
                              (UpgradeType.MAG_GLASS, "mag_glass"), (UpgradeType.COFFEE, "coffee"),
                              (UpgradeType.POOL_FLOATIE, "pool_floatie")):
            if getattr(counts, name) > 0:
                action.chosen_upgrade = upgrade
                return action
