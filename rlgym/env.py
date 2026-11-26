"""Gymnasium-style single-agent environment over game_API, with bots as the other players.

    env = BuckshotEnv(["bots/greedy_bot"], num_players=2, agent_seat=0)
    obs, info = env.reset(seed=0)
    while True:
        action = policy(obs, info["action_mask"])
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break

The observation is a fixed-length float vector built only from the player's own observation.
Seats are rotated so the agent is always seat 0. Actions follow rlgym.actions (Discrete(16)).
Faults work as in engine.run_match: an illegal action or a bot exception is a strike, and the
engine's fallback move is played instead. Two strikes eliminate the player.
"""
import random
from typing import Any, List, Optional, Sequence, Tuple

import game_API as api
from engine.limits import Limits
from engine.run_match import _fallback_pick, _fallback_play, _placements
from schemas import *

from .actions import FIELD_OF, N_ACTIONS, UPGRADE_FIELDS, action_mask, decode, is_play_obs
from .belief import p_next_live, p_next_live_naive
from .loader import LoadedBot
from .rewards import PlacementReward, Reward, Transition

try:  # gymnasium is optional; the environment works without it
    import gymnasium
    from gymnasium import spaces
    _Base = gymnasium.Env
except ImportError:  # pragma: no cover - depends on the host
    gymnasium, spaces, _Base = None, None, object

MAX_SEATS = 4
SEAT_FEATURES = 9
OBS_SIZE = MAX_SEATS * SEAT_FEATURES + 24
_COUNT_SCALE = 50.0


def encode_observation(obs: Any) -> List[float]:
    """Fixed-length features from an Obs_PLAY or Obs_PICK_UPGRADES, rotated so obs.turn is seat 0."""
    k, me = len(obs.players), obs.turn
    vec: List[float] = []
    for rel in range(MAX_SEATS):
        if rel >= k:
            vec += [0.0] * SEAT_FEATURES
            continue
        p = obs.players[(me + rel) % k]
        vec += [1.0, float(p.health > 0), p.health / obs.max_health]
        vec += [getattr(p.upgrades, f) / 15.0 for f in UPGRADE_FIELDS]
        vec.append(float(p.has_pool_floatie_on))
    play = is_play_obs(obs)
    vec += [float(play), float(not play), obs.session_no / 10.0]
    vec += [float(k == n) for n in (2, 3, 4)]
    if play:
        ej = obs.ejections
        vec += [x / _COUNT_SCALE for x in (obs.lives_init, obs.blanks_init, obs.rounds_remaining,
                                           obs.lives_shot, obs.blanks_shot, ej.lives_ejected,
                                           ej.blanks_ejected, ej.unknowns_ejected)]
        vec += [float(obs.next_round == v) for v in (NextRound.UNKNOWN, NextRound.LIVE, NextRound.BLANK)]
        vec += [p_next_live(obs), p_next_live_naive(obs)]
        vec += [0.0] * 5
    else:
        vec += [0.0] * 13
        vec += [getattr(obs.available_upgrades, f) / _COUNT_SCALE for f in UPGRADE_FIELDS]
    assert len(vec) == OBS_SIZE
    return vec


class _Discrete:
    """Stand-in for gymnasium.spaces.Discrete when gymnasium is not installed."""

    def __init__(self, n: int):
        self.n = n

    def sample(self, mask: Optional[Sequence[bool]] = None) -> int:
        return random.choice([i for i in range(self.n) if mask is None or mask[i]])


class BuckshotEnv(_Base):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, opponents: Sequence[Any], num_players: int = 2, agent_seat: int = 0,
                 reward: Optional[Reward] = None, limits: Limits = Limits()):
        """opponents: num_players - 1 bot directories (reloaded every episode) or bot objects."""
        if len(opponents) != num_players - 1:
            raise ValueError("need exactly num_players - 1 opponents")
        if not 0 <= agent_seat < num_players:
            raise ValueError("agent_seat out of range")
        self.opponent_specs = list(opponents)
        self.num_players, self.agent_seat = num_players, agent_seat
        self.reward_fn = reward or PlacementReward()
        self.limits = limits
        if spaces is not None:
            self.action_space = spaces.Discrete(N_ACTIONS)
            self.observation_space = spaces.Box(-1.0, 2.0, shape=(OBS_SIZE,))
        else:
            self.action_space = _Discrete(N_ACTIONS)
            self.observation_space = None
        self.state: Optional[api.GameState] = None

    # --- gym API -------------------------------------------------------------------------------
    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None) -> Tuple[List[float], dict]:
        if seed is None:
            seed = random.randrange(2**31)
        self.seed = seed
        self.state = api.initGame(seed, self.num_players)
        self.fallback_rng = random.Random(seed ^ 0x5EED)
        self.strikes = [0] * self.num_players
        self.faults = [0] * self.num_players
        self.steps = 0
        others = [s for s in range(self.num_players) if s != self.agent_seat]
        self.bots = {seat: LoadedBot(spec) if isinstance(spec, str) else spec
                     for seat, spec in zip(others, self.opponent_specs)}
        self._run_opponents()
        return self._observe()

    def step(self, action: int) -> Tuple[List[float], float, bool, bool, dict]:
        state = self.state
        if state is None or self._done():
            raise RuntimeError("call reset() before step()")
        seat = self.agent_seat
        prev_health = [p.health for p in state.players]
        obs = self._raw_obs()
        illegal = not (0 <= action < N_ACTIONS) or not action_mask(obs)[action]
        if illegal:
            self._strike(seat)
        else:
            self._apply(decode(action, obs))
        damage = sum(max(0, prev_health[i] - p.health) for i, p in enumerate(state.players) if i != seat)
        self._run_opponents()
        obs_vec, info = self._observe()
        info["illegal_action"] = illegal
        terminated = state.game_over or state.players[seat].health <= 0
        truncated = not terminated and self.steps >= self.limits.max_actions
        placement = _placements(state)[seat] if terminated or truncated else None
        info["placement"] = placement
        reward = self.reward_fn(Transition(prev_health, [p.health for p in state.players], seat,
                                           state.max_health, damage, placement))
        return obs_vec, reward, terminated, truncated, info

    def render(self) -> str:
        s = self.state
        hp = " ".join(f"P{i}:{p.health}" for i, p in enumerate(s.players))
        return f"session {s.session_no} stage {s.stage.value} turn {s.turn} | {hp} | {s.rounds_remaining} shells"

    # --- internals -----------------------------------------------------------------------------
    def _raw_obs(self) -> Any:
        s = self.state
        return api.play_observation(s) if s.stage == Stage.PLAY else api.upgrade_observation(s)

    def _observe(self) -> Tuple[List[float], dict]:
        if self._done():
            return [0.0] * OBS_SIZE, {"action_mask": [False] * N_ACTIONS, "seed": self.seed}
        obs = self._raw_obs()
        return encode_observation(obs), {"action_mask": action_mask(obs), "stage": self.state.stage.value,
                                         "p_live": p_next_live(obs) if is_play_obs(obs) else None,
                                         "seed": self.seed}

    def _done(self) -> bool:
        s = self.state
        return s.game_over or s.players[self.agent_seat].health <= 0 or self.steps >= self.limits.max_actions

    def _apply(self, action: Any) -> None:
        self.steps += 1
        (api.step_PLAY if self.state.stage == Stage.PLAY else api.step_PICK_UPGRADE)(self.state, action)

    def _strike(self, seat: int) -> None:
        """An engine fault: count it, then play the engine's fallback move or eliminate the player."""
        self.strikes[seat] += 1
        self.faults[seat] += 1
        if self.strikes[seat] >= self.limits.max_strikes:
            self.steps += 1
            api.eliminate_player(self.state, seat)
        elif self.state.stage == Stage.PLAY:
            self._apply(_fallback_play(self.state, self.fallback_rng))
        else:
            self._apply(_fallback_pick(self.state))

    def _run_opponents(self) -> None:
        s = self.state
        while not self._done() and s.turn != self.agent_seat:
            seat, bot = s.turn, self.bots[s.turn]
            obs = self._raw_obs()
            try:
                action = bot.play(obs) if s.stage == Stage.PLAY else bot.pick_upgrade(obs)
                self._apply(action)
            except Exception:
                self._strike(seat)
