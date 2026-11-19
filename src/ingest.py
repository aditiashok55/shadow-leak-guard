"""Ingest: chunk docs, embed with Ollama, store in ChromaDB with ACL metadata.

ACL metadata (sensitivity + allowed_roles) is stored on every chunk but is NOT
enforced during retrieval in the baseline. Run:

    python src/ingest.py
"""
from __future__ import annotations

import chromadb

from acl import doc_allowed_roles, doc_sensitivity
from config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DOCS_DIR,
    EMBED_PROVIDER,
)
from llm import embed_many


def _collection_name() -> str:
    """Isolate collections per embedding provider (vector dims differ)."""
    suffix = "st" if EMBED_PROVIDER == "sentence-transformers" else "ollama"
    return f"{COLLECTION_NAME}_{suffix}"


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Simple character-window chunking with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if c]


def get_collection(reset: bool = False):
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    name = _collection_name()
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    # embedding_function=None: we ALWAYS supply our own vectors (add/query use
    # embeddings=/query_embeddings=). This stops Chroma from lazily fetching its
    # default ONNX MiniLM model from the network, which otherwise stalls startup.
    return client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}, embedding_function=None
    )


def ingest() -> int:
    collection = get_collection(reset=True)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for path in sorted(DOCS_DIR.glob("*.md")):
        doc_id = path.stem
        text = path.read_text()
        sensitivity = doc_sensitivity(doc_id)
        allowed = ",".join(doc_allowed_roles(doc_id))
        for i, chunk in enumerate(chunk_text(text)):
            ids.append(f"{doc_id}::{i}")
            documents.append(chunk)
            metadatas.append(
                {
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "sensitivity": sensitivity,      # stored, not enforced (baseline)
                    "allowed_roles": allowed,
                    "source": path.name,
                }
            )

    print(f"Embedding {len(documents)} chunks from {DOCS_DIR} ...")
    embeddings = embed_many(documents)
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    print(f"Ingested {len(documents)} chunks into collection '{_collection_name()}'.")
    return len(documents)


def ensure_ingested() -> int:
    """Build the index on first use if it's empty (used by the cloud UI).

    Lets a fresh deploy self-bootstrap: no prebuilt .chroma needed in the repo.
    """
    collection = get_collection(reset=False)
    if collection.count() == 0:
        return ingest()
    return collection.count()


if __name__ == "__main__":
    ingest()
