"""Thin Ollama client for embeddings and chat. Deterministic (temperature 0)."""
from __future__ import annotations

import requests

from config import EMBED_MODEL, LLM_MODEL, OLLAMA_HOST, TEMPERATURE


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


def generate(system: str, prompt: str) -> str:
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
    return resp.json()["message"]["content"].strip()
