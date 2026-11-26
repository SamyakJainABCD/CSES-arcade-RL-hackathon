"""Task T3 starting point: always shoots the first living opponent."""
from schemas import *


class Bot:
    def play(self, obs):
        action = Action_PLAY()
        action.action, action.useUpgrade = ActionType.SHOOT, None
        action.target = next(i for i, p in enumerate(obs.players) if i != obs.turn and p.health > 0)
        return action

    def pick_upgrade(self, obs):
        action = Action_PICK_UPGRADES()
        action.chosen_upgrade = next(u for u in UpgradeType if getattr(obs.available_upgrades, u.value.lower()) > 0)
        return action
