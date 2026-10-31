"""Shared paths and config constants for shadow-leak-guard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"
ROLES_PATH = DATA_DIR / "roles.json"
ACL_PATH = DATA_DIR / "acl.json"
TRACES_DIR = ROOT / "traces"
CHROMA_DIR = ROOT / ".chroma"

# Ollama models (local, deterministic)
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.1:latest"
OLLAMA_HOST = "http://localhost:11434"

# Retrieval / generation knobs
TOP_K = 5
CHUNK_SIZE = 600          # characters per chunk (simple char-based chunking)
CHUNK_OVERLAP = 100
TEMPERATURE = 0.0         # deterministic
COLLECTION_NAME = "shadow_leak_docs"
