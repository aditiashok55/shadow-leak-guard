"""LLM + embedding client, provider-pluggable.

Providers (selected in config, so the same code runs locally and in the cloud):
  LLM_PROVIDER   = "ollama" (local)  | "groq" (hosted, OpenAI-compatible chat)
  EMBED_PROVIDER = "ollama" (local)  | "sentence-transformers" (CPU, free)

Local dev defaults to Ollama (unchanged). Cloud deploy sets LLM_PROVIDER=groq +
EMBED_PROVIDER=sentence-transformers via secrets, with no code changes elsewhere.
All generation is deterministic (temperature 0).
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from config import (
    EMBED_MODEL,
    EMBED_PROVIDER,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    LLM_MODEL,
    LLM_PROVIDER,
    OLLAMA_HOST,
    ST_EMBED_MODEL,
    TEMPERATURE,
)


def _enable_hf_offline_if_cached(model_name: str) -> None:
    """If the HF model weights are already on disk, switch HF fully offline.

    CRITICAL: this must run *before* `huggingface_hub` / `sentence_transformers`
    are imported, because huggingface_hub snapshots `HF_HUB_OFFLINE` into a module
    constant at import time. Setting the env var after import has no effect, which
    caused multi-minute stalls while HF tried (and slowly failed) to reach the Hub
    on every process start. We check the cache via the filesystem (no HF import)
    so we can decide before anything loads.
    """
    import os

    # Respect an explicit user choice if already set.
    if os.environ.get("HF_HUB_OFFLINE") is not None:
        return

    hub = os.environ.get("HF_HOME")
    hub_dir = (
        os.path.join(hub, "hub")
        if hub
        else os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    )
    # HF cache folder name: models--<org>--<name>
    folder = "models--" + model_name.replace("/", "--")
    snapshots = os.path.join(hub_dir, folder, "snapshots")
    if os.path.isdir(snapshots) and os.listdir(snapshots):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        # Not cached yet (e.g. first run in the cloud): allow a download but cap
        # the metadata check so it can never hang for minutes.
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")


# Run the offline decision at import time, before any HF library is imported.
if EMBED_PROVIDER == "sentence-transformers":
    _enable_hf_offline_if_cached(ST_EMBED_MODEL)


@dataclass
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---------------------------------------------------------------- embeddings --
_ST_MODEL = None  # lazily-loaded sentence-transformers model (cloud/CPU path)


def _get_st_model():
    """Load (once) and return the sentence-transformers model.

    Offline-vs-online was already decided at import time by
    `_enable_hf_offline_if_cached`, so by the time we import sentence_transformers
    here the HF_HUB_OFFLINE constant is correct and a cached model loads in <1s
    with zero network round-trips.
    """
    global _ST_MODEL
    if _ST_MODEL is not None:
        return _ST_MODEL

    from sentence_transformers import SentenceTransformer

    _ST_MODEL = SentenceTransformer(ST_EMBED_MODEL)
    return _ST_MODEL


def _embed_ollama(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def _embed_st(text: str) -> list[float]:
    model = _get_st_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed(text: str) -> list[float]:
    if EMBED_PROVIDER == "sentence-transformers":
        return _embed_st(text)
    return _embed_ollama(text)


def embed_many(texts: list[str]) -> list[list[float]]:
    if EMBED_PROVIDER == "sentence-transformers":
        model = _get_st_model()
        return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]
    return [_embed_ollama(t) for t in texts]


# ---------------------------------------------------------------- generation --
def _generate_ollama(system: str, prompt: str) -> Generation:
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


def _generate_groq(system: str, prompt: str) -> Generation:
    """OpenAI-compatible chat completion via Groq."""
    if not GROQ_API_KEY:
        raise RuntimeError(
            "LLM_PROVIDER=groq but GROQ_API_KEY is not set. Add it to your env "
            "or .streamlit/secrets.toml."
        )
    resp = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "shadow-leak-guard/1.0",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": TEMPERATURE,
            "seed": 42,
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return Generation(
        text=data["choices"][0]["message"]["content"].strip(),
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


def generate_ex(system: str, prompt: str) -> Generation:
    """Chat completion returning text + token counts (for tracing)."""
    if LLM_PROVIDER == "groq":
        return _generate_groq(system, prompt)
    return _generate_ollama(system, prompt)


def generate(system: str, prompt: str) -> str:
    """Back-compat wrapper returning just the text."""
    return generate_ex(system, prompt).text


