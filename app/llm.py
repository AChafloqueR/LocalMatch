"""Capa mínima para modelos de lenguaje. Sin dependencias externas.

LLM_PROVIDER = mock | ollama | anthropic
Si el proveedor falla, devuelve None y el sistema usa su método por reglas.
"""
import json
import os
import re
import urllib.request


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "mock").lower()


def _post(url: str, payload: dict, headers: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def complete(prompt: str, system: str = "") -> str | None:
    p = provider()
    try:
        if p == "ollama":
            out = _post(
                os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/generate",
                {"model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"), "prompt": prompt, "system": system, "stream": False},
                {"Content-Type": "application/json"},
            )
            return out.get("response")
        if p == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if not key:
                return None
            out = _post(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                    "max_tokens": 800,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            return "".join(b.get("text", "") for b in out.get("content", []))
    except Exception:
        return None
    return None


def complete_json(prompt: str, system: str = "") -> dict | None:
    text = complete(prompt, system)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
