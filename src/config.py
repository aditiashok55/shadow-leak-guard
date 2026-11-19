"""Shared paths and config constants for shadow-leak-guard."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"
ROLES_PATH = DATA_DIR / "roles.json"
ACL_PATH = DATA_DIR / "acl.json"
TRACES_DIR = ROOT / "traces"
CHROMA_DIR = ROOT / ".chroma"


def _secret(name: str, default: str = "") -> str:
    """Read a setting from env first, then Streamlit secrets (if available).

    This lets the same code run locally (env / .env) and on Streamlit Cloud
    (st.secrets) without changes. Never hard-code keys.
    """
    val = os.getenv(name)
    if val:
        return val
    try:  # Streamlit may not be installed in CLI-only contexts.
        import streamlit as st  # type: ignore

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


# --- LLM provider (local Ollama for dev, Groq for cloud deploy) ---------------
# LLM_PROVIDER = "ollama" (default, local) | "groq" (hosted, OpenAI-compatible)
LLM_PROVIDER = _secret("LLM_PROVIDER", "ollama").strip().lower()

# Ollama (local) models + host
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.1:latest"
OLLAMA_HOST = _secret("OLLAMA_HOST", "http://localhost:11434")

# Groq (cloud) — OpenAI-compatible chat API. Key comes from env / st.secrets.
# NOTE: must be a *chat/generation* model. Do NOT use classifier/guard models
# like "meta-llama/llama-prompt-guard-*" or "*-safeguard-*", nor audio models
# like "whisper-*" / "orpheus-*" — they don't generate answers, so the pipeline
# will appear to hang.
# Good options: "openai/gpt-oss-120b" (best), "openai/gpt-oss-20b" (verified),
# "qwen/qwen3.8-27b".
GROQ_API_KEY = _secret("GROQ_API_KEY", "")
GROQ_MODEL = _secret("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_BASE_URL = _secret("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# --- Embedding provider -------------------------------------------------------
# EMBED_PROVIDER = "ollama" (default, local) | "sentence-transformers" (CPU, cloud)
EMBED_PROVIDER = _secret("EMBED_PROVIDER", "ollama").strip().lower()
ST_EMBED_MODEL = _secret("ST_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Retrieval / generation knobs
TOP_K = 5
CHUNK_SIZE = 600          # characters per chunk (simple char-based chunking)
CHUNK_OVERLAP = 100
TEMPERATURE = 0.0         # deterministic
COLLECTION_NAME = "shadow_leak_docs"

# Layer 2 (graph lineage) knobs
ENTITIES_PATH = DATA_DIR / "entities.json"
ENTITY_CACHE_PATH = DATA_DIR / ".entity_cache.json"
GRAPH_HOP_LIMIT = 2       # doc -> entity -> restricted-doc = 2 hops (one shared entity)

# Graph backend (Phase 2, U2): "networkx" (default, in-memory) or "neo4j".
GRAPH_BACKEND = os.getenv("GRAPH_BACKEND", "networkx").strip().lower()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")
