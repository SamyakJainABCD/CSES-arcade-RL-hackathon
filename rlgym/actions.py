"""One fixed discrete action space for both stages, and legality computed from observations only.

Index layout (seats are relative to the acting player, so 0 is always "me"):
  0-3    SHOOT relative seat 0..3
  4-7    USE JUICE, COFFEE, MAG_GLASS, HAND_SAW
  8-10   USE POOL_FLOATIE on relative seat 1..3
  11-15  PICK JUICE, COFFEE, MAG_GLASS, POOL_FLOATIE, HAND_SAW
"""
import random
from typing import Any, List, Optional

from schemas import *

N_ACTIONS = 16
UPGRADE_FIELDS = ("juice", "coffee", "mag_glass", "pool_floatie", "hand_saw")
FIELD_OF = {UpgradeType.JUICE: "juice", UpgradeType.COFFEE: "coffee", UpgradeType.MAG_GLASS: "mag_glass",
            UpgradeType.POOL_FLOATIE: "pool_floatie", UpgradeType.HAND_SAW: "hand_saw"}
_USE_ORDER = (UpgradeType.JUICE, UpgradeType.COFFEE, UpgradeType.MAG_GLASS, UpgradeType.HAND_SAW)
_PICK_ORDER = (UpgradeType.JUICE, UpgradeType.COFFEE, UpgradeType.MAG_GLASS, UpgradeType.POOL_FLOATIE,
               UpgradeType.HAND_SAW)


def is_play_obs(obs: Any) -> bool:
    return hasattr(obs, "rounds_remaining")


def _play(kind: ActionType, upgrade: Optional[UpgradeType], target: Optional[int]) -> Action_PLAY:
    action = Action_PLAY()
    action.action, action.useUpgrade, action.target = kind, upgrade, target
    return action


def _pick(upgrade: UpgradeType) -> Action_PICK_UPGRADES:
    action = Action_PICK_UPGRADES()
    action.chosen_upgrade = upgrade
    return action


def _seat(me: int, rel: int, k: int) -> int:
    if rel >= k:
        raise ValueError(f"relative seat {rel} does not exist in a {k}-player game")
    return (me + rel) % k


def stage_indices(obs: Any) -> range:
    """The action indices that belong to this observation's stage."""
    return range(0, 11) if is_play_obs(obs) else range(11, N_ACTIONS)


def decode(index: int, obs: Any) -> Any:
    """Turn an action index into an engine action for the player whose observation this is."""
    k, me = len(obs.players), obs.turn
    if 0 <= index <= 3:
        return _play(ActionType.SHOOT, None, _seat(me, index, k))
    if 4 <= index <= 7:
        return _play(ActionType.USE_UPGRADE, _USE_ORDER[index - 4], None)
    if 8 <= index <= 10:
        return _play(ActionType.USE_UPGRADE, UpgradeType.POOL_FLOATIE, _seat(me, index - 7, k))
    if 11 <= index <= 15:
        return _pick(_PICK_ORDER[index - 11])
    raise ValueError(f"action index {index} out of range")


def encode(action: Any, obs: Any) -> Optional[int]:
    """Inverse of decode; None if the action is outside the action space."""
    k, me = len(obs.players), obs.turn
    if isinstance(action, Action_PICK_UPGRADES) or hasattr(action, "chosen_upgrade"):
        return 11 + _PICK_ORDER.index(UpgradeType(action.chosen_upgrade))
    kind = ActionType(action.action)
    target = getattr(action, "target", None)
    rel = (target - me) % k if isinstance(target, int) and not isinstance(target, bool) and 0 <= target < k else None
    if kind == ActionType.SHOOT:
        return rel
    upgrade = UpgradeType(action.useUpgrade)
    if upgrade == UpgradeType.POOL_FLOATIE:
        return 7 + rel if rel else None
    return 4 + _USE_ORDER.index(upgrade)


def action_mask(obs: Any) -> List[bool]:
    """mask[i] is True iff decode(i, obs) is legal. Uses only public observation fields."""
    mask = [False] * N_ACTIONS
    k, me = len(obs.players), obs.turn
    if not is_play_obs(obs):
        for i, upgrade in enumerate(_PICK_ORDER):
            mask[11 + i] = getattr(obs.available_upgrades, FIELD_OF[upgrade]) > 0
        return mask
    mine = obs.players[me].upgrades
    has_shell = obs.rounds_remaining > 0
    for rel in range(k):
        mask[rel] = has_shell and obs.players[(me + rel) % k].health > 0
    mask[4] = mine.juice > 0
    mask[5] = mine.coffee > 0 and has_shell
    mask[6] = mine.mag_glass > 0 and has_shell
    mask[7] = mine.hand_saw > 0
    for rel in range(1, k):
        other = obs.players[(me + rel) % k]
        mask[7 + rel] = mine.pool_floatie > 0 and other.health > 0 and not other.has_pool_floatie_on
    return mask


def legal_indices(obs: Any) -> List[int]:
    return [i for i, ok in enumerate(action_mask(obs)) if ok]


def random_legal(obs: Any, rng: random.Random) -> Any:
    """Uniformly random legal action; used by the verifier and as a baseline policy."""
    return decode(rng.choice(legal_indices(obs)), obs)
