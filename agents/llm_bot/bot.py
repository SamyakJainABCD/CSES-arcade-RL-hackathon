"""A language-model player: renders the observation as text, asks a model for a JSON action.

params.json / init params:
  provider  "mock" (offline, default), "anthropic" (ANTHROPIC_API_KEY) or "openai" (OPENAI_API_KEY)
  model     provider model id (provider default if omitted)
  log       path of a JSONL file that receives every prompt, response, parse result and usage

In-process only: it needs the network and rlgym, neither of which exists in the sandbox, and
model latency is far above the engine's 50 ms limit. Evaluate it with `python -m rlgym.llm_eval`.
A reply that cannot be parsed counts as a parse failure, and the bot then shoots the next
opponent (or makes its first legal pick). A parsed id that is not legal is passed to the engine, which faults it as illegal.
"""
import json
import re
import time

import providers
import render
from rlgym.actions import N_ACTIONS, decode
from schemas import *


class Bot:
    def init(self, params=None):
        params = params or {}
        self.provider_name = params.get("provider", "mock")
        self.call = providers.PROVIDERS[self.provider_name]
        self.model = params.get("model")
        self.log_path = params.get("log")
        self.stats = {"calls": 0, "parse_failures": 0, "off_list": 0, "input_tokens": 0, "output_tokens": 0,
                      "provider_errors": 0, "seconds": 0.0}

    def play(self, obs):
        return self._decide(obs)

    def pick_upgrade(self, obs):
        return self._decide(obs)

    def _decide(self, obs):
        user, legal = render.render(obs)
        started = time.perf_counter()
        try:
            text, usage = self.call(render.SYSTEM, user, self.model)
        except Exception as exc:  # network or API failure counts as an unparseable reply
            text, usage = "", {}
            self.stats["provider_errors"] += 1
            error = repr(exc)
        else:
            error = None
        elapsed = time.perf_counter() - started
        index = self._parse(text)
        self.stats["calls"] += 1
        self.stats["seconds"] += elapsed
        self.stats["input_tokens"] += usage.get("input_tokens", 0)
        self.stats["output_tokens"] += usage.get("output_tokens", 0)
        action = None
        if index is not None:
            try:
                action = decode(index, obs)
            except ValueError:
                index = None
        if index is None:
            self.stats["parse_failures"] += 1
            action = decode(next((i for i in (1, 2, 3) if i in legal), min(legal)), obs)
        elif index not in legal:
            self.stats["off_list"] += 1
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"user": user, "response": text, "parsed": index, "legal": sorted(legal),
                                    "usage": usage, "seconds": round(elapsed, 3), "error": error}) + "\n")
        return action

    @staticmethod
    def _parse(text):
        match = re.search(r"\{.*?\}", text or "", re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0)).get("action")
        except (ValueError, AttributeError):
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < N_ACTIONS:
            return None
        return value
