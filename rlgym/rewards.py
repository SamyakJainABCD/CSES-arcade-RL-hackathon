"""Reward functions for BuckshotEnv. Each maps one agent transition to a float.

PlacementReward        sparse; equals the leaderboard's placement points at the end. Use this.
PotentialShapedReward  PlacementReward + gamma * phi(s') - phi(s), phi = health lead.
                       Potential-based shaping keeps the optimal policy unchanged
                       (Ng, Harada & Russell, "Policy invariance under reward
                       transformations", ICML 1999) as long as phi(terminal) = 0.
NaiveDamageReward      counter-example: +1 per point of damage the agent deals. It ignores
                       who survives. In 4-player tables it ranks policies differently from
                       the leaderboard: the bot that deals the most damage is not the one
                       with the most points. Measured by `python -m redteam.run`; see
                       FINDINGS.md.
"""
from dataclasses import dataclass
from typing import List, Optional

from engine.scoring import placement_points


@dataclass
class Transition:
    prev_health: List[int]       # every seat's health before the agent acted
    health: List[int]            # every seat's health when control returns to the agent (or at the end)
    seat: int                    # the agent's seat
    max_health: int
    damage_dealt: int            # health the agent's own action removed from opponents
    placement: Optional[int]     # final placement once the episode is over, else None


class Reward:
    name = "reward"

    def __call__(self, t: Transition) -> float:
        raise NotImplementedError


class PlacementReward(Reward):
    """(k-1) - 2*(place-1) at the end, 0 otherwise: the return is exactly the leaderboard score."""
    name = "placement"

    def __call__(self, t: Transition) -> float:
        return 0.0 if t.placement is None else float(placement_points(t.placement, len(t.health)))


class PotentialShapedReward(Reward):
    """Placement reward plus potential-based shaping on the agent's health lead."""
    name = "shaped"

    def __init__(self, scale: float = 1.0, gamma: float = 1.0):
        self.scale, self.gamma = scale, gamma
        self.base = PlacementReward()

    def phi(self, health: List[int], seat: int, max_health: int) -> float:
        best_other = max(h for i, h in enumerate(health) if i != seat)
        return self.scale * (health[seat] - best_other) / max_health

    def __call__(self, t: Transition) -> float:
        before = self.phi(t.prev_health, t.seat, t.max_health)
        after = 0.0 if t.placement is not None else self.phi(t.health, t.seat, t.max_health)
        return self.base(t) + self.gamma * after - before


class NaiveDamageReward(Reward):
    """Hackable proxy kept as a documented counter-example; do not train on this."""
    name = "damage"

    def __call__(self, t: Transition) -> float:
        return float(t.damage_dealt)


REWARDS = {cls.name: cls for cls in (PlacementReward, PotentialShapedReward, NaiveDamageReward)}
