"""Graph lineage store for Layer 2 (M3).

Model:
    (Document {sensitivity}) -[:MENTIONS]-> (Entity {sensitivity})
    Entity.sensitivity = max sensitivity of the documents that mention it.

The `GraphStore` interface hides the backend so a `Neo4jGraphStore` can swap in
later (Phase 2 / plan-v2 U2) without touching the guard logic.

Lineage question Layer 2 asks:
    "Does this allowed document share an entity with a document the current role
     is NOT cleared to see, within `hop_limit` hops?"
If yes, that shared entity is a bridge that could leak restricted facts by
inference, even though the document itself passed the ACL check.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import networkx as nx

from acl import doc_sensitivity
from config import ENTITIES_PATH, GRAPH_HOP_LIMIT


@dataclass
class Bridge:
    """A lineage path from an allowed doc to a document the role cannot access."""

    entity: str
    entity_sensitivity: str
    target_doc: str
    target_sensitivity: str
    hops: int


class GraphStore(ABC):
    """Backend-agnostic lineage interface."""

    @abstractmethod
    def entities_for_doc(self, doc_id: str) -> list[str]: ...

    @abstractmethod
    def docs_for_entity(self, entity: str) -> list[str]: ...

    @abstractmethod
    def entity_sensitivity(self, entity: str) -> str: ...

    @abstractmethod
    def bridges_to_forbidden(
        self, doc_id: str, allowed_sensitivities: list[str], hop_limit: int
    ) -> list[Bridge]:
        """Return bridges from `doc_id` to any doc whose sensitivity is NOT in
        `allowed_sensitivities`, reachable within `hop_limit` hops via entities."""
        ...


class NetworkXGraphStore(GraphStore):
    """In-memory lineage graph built from the hand-labeled entity map."""

    def __init__(self, doc_entities: dict[str, list[str]],
                 entity_sensitivity: dict[str, str] | None = None):
        self.g = nx.Graph()
        self._doc_entities = doc_entities
        self._entity_sensitivity = entity_sensitivity or {}
        self._build()

    @classmethod
    def from_file(cls, path=ENTITIES_PATH) -> "NetworkXGraphStore":
        data = json.loads(path.read_text())
        return cls(data["documents"], data.get("entity_sensitivity", {}))

    def _build(self) -> None:
        entity_docs: dict[str, list[str]] = {}
        for doc_id, entities in self._doc_entities.items():
            for e in entities:
                entity_docs.setdefault(e, []).append(doc_id)

        for doc_id in self._doc_entities:
            self.g.add_node(("doc", doc_id), kind="doc",
                            sensitivity=doc_sensitivity(doc_id))

        for entity, docs in entity_docs.items():
            # Explicit label if provided; otherwise generic vocabulary -> public.
            e_sens = self._entity_sensitivity.get(entity, "public")
            self.g.add_node(("entity", entity), kind="entity", sensitivity=e_sens)
            for d in docs:
                self.g.add_edge(("doc", d), ("entity", entity))

    # --- GraphStore interface ---
    def entities_for_doc(self, doc_id: str) -> list[str]:
        node = ("doc", doc_id)
        if node not in self.g:
            return []
        return [n[1] for n in self.g.neighbors(node) if n[0] == "entity"]

    def docs_for_entity(self, entity: str) -> list[str]:
        node = ("entity", entity)
        if node not in self.g:
            return []
        return [n[1] for n in self.g.neighbors(node) if n[0] == "doc"]

    def entity_sensitivity(self, entity: str) -> str:
        node = ("entity", entity)
        return self.g.nodes[node]["sensitivity"] if node in self.g else "restricted"

    def bridges_to_forbidden(
        self, doc_id: str, allowed_sensitivities: list[str],
        hop_limit: int = GRAPH_HOP_LIMIT,
    ) -> list[Bridge]:
        """Flag entities in `doc_id` that (a) are themselves labeled above the
        role's clearance AND (b) also appear in a document the role cannot see.

        Condition (a) ignores generic overlap vocabulary (labeled 'public'), so
        shared wording like "team changes" never triggers a false block. Condition
        (b) proves the entity actually bridges to forbidden content, not just that
        it is sensitive in isolation.
        """
        source = ("doc", doc_id)
        if source not in self.g:
            return []
        bridges: list[Bridge] = []
        seen: set[tuple[str, str]] = set()

        for entity in self.entities_for_doc(doc_id):
            e_sens = self.g.nodes[("entity", entity)]["sensitivity"]
            if e_sens in allowed_sensitivities:
                continue  # entity itself is within clearance -> not a leak
            for target_doc in self.docs_for_entity(entity):
                if target_doc == doc_id:
                    continue
                t_sens = doc_sensitivity(target_doc)
                if t_sens in allowed_sensitivities:
                    continue  # target viewable by role -> not evidence of a leak
                hops = 2  # doc -> entity -> target_doc
                if hops > hop_limit:
                    continue
                key = (entity, target_doc)
                if key in seen:
                    continue
                seen.add(key)
                bridges.append(
                    Bridge(entity=entity, entity_sensitivity=e_sens,
                           target_doc=target_doc, target_sensitivity=t_sens,
                           hops=hops)
                )
        return bridges


# Module-level singleton (cheap to build; swap for Neo4jGraphStore in Phase 2).
_STORE: GraphStore | None = None


def get_store() -> GraphStore:
    global _STORE
    if _STORE is None:
        _STORE = NetworkXGraphStore.from_file()
    return _STORE
