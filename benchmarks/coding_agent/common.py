"""Shared pieces of the coding-agent benchmark: task table, workspace assembly, hashing."""
import hashlib
import os
import shutil
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TASKS = {"T1": "T1_belief", "T2": "T2_bugfix", "T3": "T3_bot"}
EDITABLE = {"T1": ["belief.py"], "T2": ["game_API.py"], "T3": ["my_bot/"]}

NAIVE_BELIEF = '''"""greedy_bot's estimator: live shells left / shells left."""


def p_next_live_naive(obs):
    if obs.next_round.value in ("LIVE", "BLANK"):
        return 1.0 if obs.next_round.value == "LIVE" else 0.0
    if obs.rounds_remaining <= 0:
        return 0.0
    ej = obs.ejections
    known_lives = obs.lives_shot + ej.lives_ejected
    return (obs.lives_init - known_lives) / (obs.rounds_remaining + ej.unknowns_ejected)
'''
GREEDY_BOT = '''"""greedy_bot: HeuristicPolicy with the naive estimator."""
import belief
import policy


class Bot:
    def init(self, params=None):
        self.policy = policy.HeuristicPolicy(belief.p_next_live_naive)

    def play(self, obs):
        return self.policy.play(obs)

    def pick_upgrade(self, obs):
        return self.policy.pick(obs)
'''


def task_name(task: str) -> str:
    key = task.split("_")[0].upper()
    if key not in TASKS:
        raise SystemExit(f"unknown task {task}; choose from {', '.join(TASKS)}")
    return key


def _copy(src: str, dst: str) -> None:
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)


def build_workspace(task: str, workspace: str) -> None:
    """Write the pristine public workspace for a task. Nothing from hidden/ or solutions/ goes in."""
    key = task_name(task)
    os.makedirs(workspace, exist_ok=True)
    _copy(os.path.join(HERE, "tasks", TASKS[key]), workspace)
    repo = lambda *p: os.path.join(REPO, *p)  # noqa: E731
    shared = ["schemas.py", "wire.py"]
    if key == "T1":
        shared += ["game_API.py"]
    elif key == "T2":
        shared += ["bots/random_bot"]
    else:
        shared += ["game_API.py", "engine", "sandbox", "bots/random_bot", "Dockerfile"]
    for path in shared:
        _copy(repo(path), os.path.join(workspace, path))
    if key == "T3":
        greedy = os.path.join(workspace, "opponents", "greedy_bot")
        os.makedirs(greedy, exist_ok=True)
        _copy(repo("bots", "greedy_bot", "policy.py"), os.path.join(greedy, "policy.py"))
        with open(os.path.join(greedy, "belief.py"), "w") as f:
            f.write(NAIVE_BELIEF)
        with open(os.path.join(greedy, "bot.py"), "w") as f:
            f.write(GREEDY_BOT)


def sha256_tree(root: str) -> Dict[str, str]:
    """{relative path: sha256} for every file under root, ignoring caches."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def tampered(task: str, workspace: str, pristine: str) -> List[str]:
    """Protected public files that are missing or differ from the pristine copy."""
    key = task_name(task)
    editable = EDITABLE[key]
    expected, actual = sha256_tree(pristine), sha256_tree(workspace)
    return sorted(path for path, digest in expected.items()
                  if not any(path == e or path.startswith(e) for e in editable) and actual.get(path) != digest)
