"""Vector search over the ChromaDB collection.

Retrieval is deliberately permission-agnostic: it returns the top-k most similar
chunks regardless of role. Enforcement is the job of Layer 1 (`guard.layer1_acl_filter`),
so the baseline (no guard) demonstrably leaks.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import TOP_K
from ingest import get_collection
from llm import embed


@dataclass
class Chunk:
    id: str
    text: str
    doc_id: str
    sensitivity: str
    allowed_roles: str
    distance: float


def retrieve(query: str, top_k: int = TOP_K) -> list[Chunk]:
    """Pure top-k vector search. No ACL enforcement here by design."""
    collection = get_collection(reset=False)
    q_emb = embed(query)
    res = collection.query(query_embeddings=[q_emb], n_results=top_k)
    chunks: list[Chunk] = []
    for cid, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        chunks.append(
            Chunk(
                id=cid,
                text=doc,
                doc_id=meta["doc_id"],
                sensitivity=meta["sensitivity"],
                allowed_roles=meta["allowed_roles"],
                distance=dist,
            )
        )
    return chunks
