"""Shared test fixtures: building states and throwaway bot directories."""
import os
import tempfile
import textwrap

import game_API as api
from schemas import *


def play_action(kind: ActionType, upgrade=None, target=None) -> Action_PLAY:
    action = Action_PLAY()
    action.action, action.useUpgrade, action.target = kind, upgrade, target
    return action


def snapshot(state: api.GameState) -> tuple:
    """Everything observable about players plus the turn, for no-change assertions."""
    players = tuple((p.health, p.has_pool_floatie_on, tuple(vars(p.upgrades).values())) for p in state.players)
    return players, state.turn, state.stage, state.rounds_remaining


def write_bot(source: str) -> str:
    """Write a bot.py into a fresh temp directory and return the directory."""
    path = tempfile.mkdtemp(prefix="testbot_")
    with open(os.path.join(path, "bot.py"), "w") as f:
        f.write(textwrap.dedent(source))
    return path
