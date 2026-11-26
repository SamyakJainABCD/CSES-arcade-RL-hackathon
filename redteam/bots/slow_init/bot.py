"""Red team: takes 3 s to initialise (limit 2 s)."""
import time

from schemas import *

def shoot_someone(obs):
    action = Action_PLAY()
    action.action, action.useUpgrade = ActionType.SHOOT, None
    action.target = next(i for i, p in enumerate(obs.players) if i != obs.turn and p.health > 0)
    return action


def pick_first(obs):
    action = Action_PICK_UPGRADES()
    action.chosen_upgrade = next(u for u in UpgradeType if getattr(obs.available_upgrades, u.value.lower()) > 0)
    return action


class Bot:
    def init(self):
        time.sleep(3)

    def play(self, obs):
        return shoot_someone(obs)

    def pick_upgrade(self, obs):
        return pick_first(obs)
