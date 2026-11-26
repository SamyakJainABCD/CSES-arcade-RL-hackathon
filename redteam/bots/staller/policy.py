"""Heuristic policy shared by greedy_bot and belief_bot; only the next-shell estimator differs."""
from typing import Callable

from schemas import *

PICK_ORDER = (UpgradeType.JUICE, UpgradeType.MAG_GLASS, UpgradeType.HAND_SAW, UpgradeType.POOL_FLOATIE,
              UpgradeType.COFFEE)
FIELD = {UpgradeType.JUICE: "juice", UpgradeType.COFFEE: "coffee", UpgradeType.MAG_GLASS: "mag_glass",
         UpgradeType.POOL_FLOATIE: "pool_floatie", UpgradeType.HAND_SAW: "hand_saw"}


def _action(kind: ActionType, upgrade=None, target=None) -> Action_PLAY:
    action = Action_PLAY()
    action.action, action.useUpgrade, action.target = kind, upgrade, target
    return action


class HeuristicPolicy:
    """Juice when hurt, look when unsure, floatie the leader, saw a known live, then shoot."""

    def __init__(self, p_live: Callable):
        self.p_live = p_live
        self.sawed = False  # a saw is already on the barrel this turn

    def play(self, obs: Obs_PLAY) -> Action_PLAY:
        me, players = obs.turn, obs.players
        mine = players[me].upgrades
        opponents = [i for i, p in enumerate(players) if i != me and p.health > 0]
        p = self.p_live(obs)
        if players[me].health < obs.max_health and mine.juice > 0:
            return _action(ActionType.USE_UPGRADE, UpgradeType.JUICE)
        if obs.next_round == NextRound.UNKNOWN and 0.0 < p < 1.0 and mine.mag_glass > 0:
            return _action(ActionType.USE_UPGRADE, UpgradeType.MAG_GLASS)
        open_targets = [i for i in opponents if not players[i].has_pool_floatie_on]
        if len(opponents) >= 2 and mine.pool_floatie > 0 and open_targets:
            leader = max(open_targets, key=lambda i: (players[i].health, -i))
            return _action(ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, leader)
        if p >= 1.0 and mine.hand_saw > 0 and not self.sawed:
            self.sawed = True
            return _action(ActionType.USE_UPGRADE, UpgradeType.HAND_SAW)
        self.sawed = False
        if p < 0.5:
            return _action(ActionType.SHOOT, target=me)
        weakest = min(opponents, key=lambda i: (players[i].health, i))
        return _action(ActionType.SHOOT, target=weakest)

    def pick(self, obs: Obs_PICK_UPGRADES) -> Action_PICK_UPGRADES:
        action = Action_PICK_UPGRADES()
        action.chosen_upgrade = next(u for u in PICK_ORDER if getattr(obs.available_upgrades, FIELD[u]) > 0)
        return action
