"""Red team: sleeps past the 50 ms decision limit."""
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
    def play(self, obs):
        time.sleep(0.2)
        return shoot_someone(obs)

    def pick_upgrade(self, obs):
        return pick_first(obs)
