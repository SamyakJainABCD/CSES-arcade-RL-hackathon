from schemas import *
from typing import List

# Tracks the entire game
class GameState:
    max_health: int
    players: List[Player]
    stage: Stage
    turn: int
    session_no: int

    # PLAY stage fields
    round_contents: List[bool]  # order of all rounds in this session. Only changes in new session.
    lives_init: int | None      # number of live rounds in gun at start of session
    blanks_init: int | None     # number of blank rounds in gun at start of session
    rounds_remaining: int       # number of rounds remaining in gun
    lives_shot: int | None      # number of live rounds that have been shot in this session
    blanks_shot: int | None     # number of blank rounds that have been shot in this  session
    damage: int | None          # damage dealt by next round. Increased by 1 when hand saw is used.
    player_ejection_view: List[EjectionStatus]  # count of ejections as seen by each player

    # PICK_UPGRADE stage fields
    available_upgrades: UpgradeCounts | None


# placeholder functions

def initGame() -> GameState:
    state = GameState()
    return state

def step_PLAY(state: GameState, action: Action_PLAY) -> GameState_PLAY:
    playerState = GameState_PLAY()
    return playerState

def step_PICK_UPGRADES(state: GameState, action: Action_PICK_UPGRADES) -> GameState_PICK_UPGRADES:
    playerState = GameState_PICK_UPGRADES()
    return playerState