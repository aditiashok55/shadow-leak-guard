"""Thin Ollama client for embeddings and chat. Deterministic (temperature 0)."""
from __future__ import annotations

from dataclasses import dataclass

import requests

from config import EMBED_MODEL, LLM_MODEL, OLLAMA_HOST, TEMPERATURE


@dataclass
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def embed(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def embed_many(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]


def generate_ex(system: str, prompt: str) -> Generation:
    """Chat completion returning text + token counts (for tracing)."""
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": TEMPERATURE, "seed": 42},
            "stream": False,
        },
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return Generation(
        text=data["message"]["content"].strip(),
        prompt_tokens=int(data.get("prompt_eval_count", 0)),
        completion_tokens=int(data.get("eval_count", 0)),
    )


def generate(system: str, prompt: str) -> str:
    """Back-compat wrapper returning just the text."""
    return generate_ex(system, prompt).text

