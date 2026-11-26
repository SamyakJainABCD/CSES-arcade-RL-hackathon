"""Text rendering of observations and legal actions for a language-model player."""
from typing import Any, Dict, List, Tuple

from rlgym.actions import FIELD_OF, UPGRADE_FIELDS, action_mask, decode, is_play_obs
from schemas import *

SYSTEM = """You are playing Buckshot Roulette, a turn-based shooting game for 2-4 players.
Rules: everyone starts with 5 health. A shotgun holds a known number of live and blank shells in an
unknown order. On your turn you shoot any living player, yourself included. A live shell removes 1
health (more with a hand saw). If you shoot yourself with a blank you take another turn; any other
shot passes the turn. Before shooting you may use upgrades, each as a separate action:
JUICE +1 health (max 5); COFFEE ejects the next shell and shows you what it was; MAG_GLASS shows you
the next shell; HAND_SAW adds 1 damage to the next live shot; POOL_FLOATIE makes another player skip
their next turn. Between rounds, players take turns picking upgrades. The last player alive wins; if
300 actions pass, survivors are ranked by health.
Reply with ONLY a JSON object of the form {"action": <id>} where <id> is one of the listed action ids."""


def _upgrades(counts: Any) -> str:
    items = [f"{name} {getattr(counts, name)}" for name in UPGRADE_FIELDS if getattr(counts, name)]
    return ", ".join(items) or "none"


def describe(index: int, obs: Any) -> str:
    action = decode(index, obs)
    if not is_play_obs(obs):
        return f"pick {action.chosen_upgrade.value}"
    who = "yourself" if action.target == obs.turn else f"P{action.target}"
    if action.action == ActionType.SHOOT:
        return f"shoot {who}"
    if action.useUpgrade == UpgradeType.POOL_FLOATIE:
        return f"use POOL_FLOATIE on {who}"
    return f"use {action.useUpgrade.value}"


def render(obs: Any) -> Tuple[str, Dict[int, str]]:
    """The user message and the {id: description} of every legal action."""
    me = obs.turn
    lines = [f"You are P{me} in a {len(obs.players)}-player game, session {obs.session_no}."]
    for i, p in enumerate(obs.players):
        tags = ["you"] if i == me else []
        if p.health <= 0:
            tags.append("eliminated")
        if p.has_pool_floatie_on:
            tags.append("will skip next turn")
        suffix = f" ({', '.join(tags)})" if tags else ""
        lines.append(f"P{i}{suffix}: health {p.health}/{obs.max_health}; upgrades: {_upgrades(p.upgrades)}")
    if is_play_obs(obs):
        ej = obs.ejections
        lines += [f"Gun this round: {obs.lives_init} live and {obs.blanks_init} blank at the start; "
                  f"{obs.rounds_remaining} shells left.",
                  f"Fired so far: {obs.lives_shot} live, {obs.blanks_shot} blank.",
                  f"Ejected by your coffee: {ej.lives_ejected} live, {ej.blanks_ejected} blank; "
                  f"ejected by others (unseen): {ej.unknowns_ejected}.",
                  f"Next shell: {obs.next_round.value if obs.next_round != NextRound.UNKNOWN else 'unknown'}."]
        lines.append("It is your PLAY turn.")
    else:
        lines.append(f"Upgrade pick stage. Available: {_upgrades(obs.available_upgrades)}.")
    legal = {i: describe(i, obs) for i, ok in enumerate(action_mask(obs)) if ok}
    lines.append("Legal actions:")
    lines += [f"  [{i}] {text}" for i, text in legal.items()]
    return "\n".join(lines), legal
