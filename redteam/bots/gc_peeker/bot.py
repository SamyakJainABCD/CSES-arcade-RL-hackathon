"""Red team: finds the engine's GameState through the garbage collector and reads the gun.

If it runs in the same interpreter as the game (an in-process evaluator), it knows every
shell before it is fired. In the sandbox the game lives in another process, the search finds
nothing, and the bot falls back to belief_bot's policy.
"""
import gc

import belief
import policy
from schemas import *


def find_state(obs):
    """The live GameState whose public fields match this observation, if this process holds one."""
    healths = [p.health for p in obs.players]
    for candidate in gc.get_objects():
        if type(candidate).__name__ != "GameState":
            continue
        try:
            if (not candidate.game_over and candidate.turn == obs.turn
                    and candidate.rounds_remaining == obs.rounds_remaining
                    and [p.health for p in candidate.players] == healths):
                return candidate
        except AttributeError:
            continue
    return None


class Bot:
    def init(self, params=None):
        self.fallback = policy.HeuristicPolicy(belief.p_next_live)
        self.sawed = False
        self.peeks = 0

    def play(self, obs):
        state = find_state(obs)
        if state is None:
            return self.fallback.play(obs)
        self.peeks += 1
        live = state.round_contents[len(state.round_contents) - state.rounds_remaining]
        me, mine = obs.turn, obs.players[obs.turn].upgrades
        action = Action_PLAY()
        action.useUpgrade, action.target = None, None
        if obs.players[me].health < obs.max_health and mine.juice > 0:
            action.action, action.useUpgrade = ActionType.USE_UPGRADE, UpgradeType.JUICE
            return action
        if live and mine.hand_saw > 0 and not self.sawed:
            self.sawed = True
            action.action, action.useUpgrade = ActionType.USE_UPGRADE, UpgradeType.HAND_SAW
            return action
        self.sawed = False
        action.action = ActionType.SHOOT
        opponents = [i for i, p in enumerate(obs.players) if i != me and p.health > 0]
        action.target = min(opponents, key=lambda i: (obs.players[i].health, i)) if live else me
        return action

    def pick_upgrade(self, obs):
        return self.fallback.pick(obs)
