"""Red team: pool floatie aimed at TARGET, which is not a valid player index."""
from schemas import *

TARGET = True


class Bot:
    def play(self, obs):
        action = Action_PLAY()
        action.useUpgrade = None
        if obs.players[obs.turn].upgrades.pool_floatie > 0:
            action.action, action.useUpgrade, action.target = ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, TARGET
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
