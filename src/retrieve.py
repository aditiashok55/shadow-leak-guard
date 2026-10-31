"""Vector search over the ChromaDB collection. ACL filtering is optional and OFF
by default (baseline leaks). Layer 1 in M2 flips `acl_filter=True`.
"""
from __future__ import annotations

from dataclasses import dataclass

from acl import is_allowed
from config import COLLECTION_NAME, TOP_K
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


def _query(query: str, top_k: int) -> list[Chunk]:
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


def retrieve(query: str, role: str, top_k: int = TOP_K, acl_filter: bool = False):
    """Return (kept_chunks, dropped_doc_ids).

    Baseline: acl_filter=False -> nothing dropped, restricted chunks flow through.
    """
    chunks = _query(query, top_k)
    if not acl_filter:
        return chunks, []
    kept, dropped = [], []
    for c in chunks:
        if is_allowed(role, c.doc_id):
            kept.append(c)
        else:
            dropped.append(c.doc_id)
    return kept, dropped
