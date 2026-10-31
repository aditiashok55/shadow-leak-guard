"""Ingest: chunk docs, embed with Ollama, store in ChromaDB with ACL metadata.

ACL metadata (sensitivity + allowed_roles) is stored on every chunk but is NOT
enforced during retrieval in the baseline. Run:

    python src/ingest.py
"""
from __future__ import annotations

import chromadb

from acl import doc_allowed_roles, doc_sensitivity
from config import CHROMA_DIR, CHUNK_OVERLAP, CHUNK_SIZE, COLLECTION_NAME, DOCS_DIR
from llm import embed_many


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
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
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
    print(f"Ingested {len(documents)} chunks into collection '{COLLECTION_NAME}'.")
    return len(documents)


if __name__ == "__main__":
    ingest()
