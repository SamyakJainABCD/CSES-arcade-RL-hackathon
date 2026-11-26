"""Model providers over urllib (standard library only). Each returns (text, usage dict)."""
import json
import os
import re
import urllib.request
from typing import Dict, Tuple


def mock(system: str, user: str, model: str) -> Tuple[str, Dict[str, int]]:
    """Offline stand-in: reads the rendered prompt and answers with a simple rule, as JSON text."""
    legal = {int(i): text for i, text in re.findall(r"\[(\d+)\] (.+)", user)}
    nxt = re.search(r"Next shell: (\w+)", user)
    hurt = re.search(r"P\d+ \(you[^)]*\): health (\d)/(\d)", user)

    def find(prefix: str):
        return next((i for i, text in legal.items() if text.startswith(prefix)), None)

    if nxt is None:  # pick stage
        choice = next(c for c in (find("pick JUICE"), find("pick MAG_GLASS"), find("pick HAND_SAW"),
                                  find("pick POOL_FLOATIE"), min(legal)) if c is not None)
    elif nxt.group(1) == "BLANK":
        choice = find("shoot yourself")
    elif nxt.group(1) == "LIVE":
        choice = find("shoot P")
    elif hurt and hurt.group(1) != hurt.group(2) and find("use JUICE") is not None:
        choice = find("use JUICE")
    else:
        choice = next(c for c in (find("use MAG_GLASS"), find("shoot P")) if c is not None)
    text = json.dumps({"action": choice})
    return text, {"input_tokens": (len(system) + len(user)) // 4, "output_tokens": len(text) // 4, "estimated": 1}


def _post(url: str, headers: Dict[str, str], body: dict, timeout: float = 60.0) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def anthropic(system: str, user: str, model: str) -> Tuple[str, Dict[str, int]]:
    """Claude Messages API. Needs ANTHROPIC_API_KEY. Server-side refusal fallback is enabled."""
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                  "anthropic-beta": "server-side-fallback-2026-07-01"},
                 {"model": model or "claude-opus-5-5", "max_tokens": 4096, "system": system,
                  "output_config": {"effort": "low"}, "fallbacks": "default",
                  "messages": [{"role": "user", "content": user}]})
    if data.get("stop_reason") == "refusal":
        return "", {"input_tokens": data["usage"]["input_tokens"], "output_tokens": data["usage"]["output_tokens"]}
    text = "".join(block.get("text", "") for block in data["content"] if block["type"] == "text")
    return text, {"input_tokens": data["usage"]["input_tokens"], "output_tokens": data["usage"]["output_tokens"]}


def openai(system: str, user: str, model: str) -> Tuple[str, Dict[str, int]]:
    """OpenAI Chat Completions API. Needs OPENAI_API_KEY."""
    data = _post("https://api.openai.com/v1/chat/completions",
                 {"authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                 {"model": model or "gpt-4.1-mini",
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    usage = data.get("usage", {})
    return data["choices"][0]["message"]["content"] or "", {"input_tokens": usage.get("prompt_tokens", 0),
                                                            "output_tokens": usage.get("completion_tokens", 0)}


PROVIDERS = {"mock": mock, "anthropic": anthropic, "openai": openai}
