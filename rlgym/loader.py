"""Load submission bots in-process, each with its own private copy of its helper modules.

The sandbox gives every bot its own process, so two bots may both ship `policy.py`. Loaded
naively into one interpreter, the second `import policy` would return the first bot's module.
LoadedBot keeps each bot's modules out of sys.modules except while that bot is running.

In-process loading is for fast training and evaluation of trusted code only. A bot can read
the interpreter's memory, including the hidden GameState (see redteam/). Graders must use
engine.run_match.
"""
import importlib.util
import inspect
import itertools
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, Optional

import schemas  # noqa: F401  shared with every bot, as in the sandbox
import wire  # noqa: F401

_SHARED = ("schemas", "wire")
_ids = itertools.count()


class LoadedBot:
    """A bot directory loaded like sandbox/runner.py does, behind the same play/pick_upgrade calls."""

    def __init__(self, path: str, params: Optional[dict] = None, name: Optional[str] = None):
        self.path = os.path.abspath(path)
        self.name = name or os.path.basename(os.path.normpath(path))
        self.params = params if params is not None else _read_params(self.path)
        self._modules: Dict[str, Any] = {}
        self._local_names = {"bot"} | {os.path.splitext(entry)[0] for entry in os.listdir(self.path)
                                       if entry.endswith(".py") or os.path.isdir(os.path.join(self.path, entry))}
        with self._active():
            spec = importlib.util.spec_from_file_location(f"_rlgym_bot_{next(_ids)}",
                                                          os.path.join(self.path, "bot.py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules["bot"] = module
            spec.loader.exec_module(module)
            try:
                self.bot = module.Bot()
            except TypeError:
                self.bot = module.Bot(self.params)
            init = getattr(self.bot, "init", None)
            if callable(init):
                init(self.params) if len(inspect.signature(init).parameters) > 0 else init()

    def play(self, obs: Any) -> Any:
        with self._active():
            return self.bot.play(obs)

    def pick_upgrade(self, obs: Any) -> Any:
        with self._active():
            return self.bot.pick_upgrade(obs)

    def _mine(self, name: str) -> bool:
        return name not in _SHARED and name.partition(".")[0] in self._local_names

    @contextmanager
    def _active(self):
        """Swap this bot's directory and private modules in; swap them back out afterwards."""
        hidden = {name: sys.modules.pop(name) for name in self._local_names | set(self._modules)
                  if name in sys.modules and self._mine(name)}
        sys.modules.update(self._modules)
        sys.path.insert(0, self.path)
        size = len(sys.modules)
        try:
            yield
        finally:
            sys.path.remove(self.path)
            names = list(sys.modules) if len(sys.modules) != size else list(self._modules)
            for name in names:
                if self._mine(name) and name in sys.modules:
                    self._modules[name] = sys.modules.pop(name)
            sys.modules.update(hidden)


def _read_params(path: str) -> dict:
    import json
    params_file = os.path.join(path, "params.json")
    if os.path.exists(params_file):
        with open(params_file) as f:
            return json.load(f)
    return {}
