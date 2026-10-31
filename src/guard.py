"""Guard layers for shadow-leak-guard.

Layer 1 (M2): deterministic ACL pre-filter. Default deny. No LLM involved.
Layer 2 (M3): graph lineage check (rule-based, NetworkX). No LLM involved.
Layer 3 (M4): LLM output guard.         (not yet implemented)

Design rule: deterministic controls first, LLM checks second.
"""
from __future__ import annotations

from dataclasses import dataclass

from acl import clearance_for, doc_sensitivity, is_allowed
from graph import Bridge, get_store
from retrieve import Chunk


@dataclass
class Dropped:
    """A chunk removed by a guard, with a machine-readable reason."""

    doc_id: str
    chunk_id: str
    sensitivity: str
    reason: str


@dataclass
class Layer1Result:
    kept: list[Chunk]
    dropped: list[Dropped]

    @property
    def dropped_doc_ids(self) -> list[str]:
        # de-duplicated, stable order
        seen: dict[str, None] = {}
        for d in self.dropped:
            seen.setdefault(d.doc_id, None)
        return list(seen.keys())


def layer1_acl_filter(chunks: list[Chunk], role: str) -> Layer1Result:
    """Deterministic, default-deny ACL enforcement.

    A chunk is kept only if the role's clearance covers the doc's sensitivity
    AND the doc exists in the ACL. Anything else is dropped with a reason.
    """
    clearance = clearance_for(role)
    kept: list[Chunk] = []
    dropped: list[Dropped] = []

    for c in chunks:
        if not clearance:
            dropped.append(Dropped(c.doc_id, c.id, c.sensitivity, "unknown_role_default_deny"))
            continue
        if is_allowed(role, c.doc_id):
            kept.append(c)
        else:
            # Distinguish "known but insufficient clearance" from "missing ACL".
            sens = doc_sensitivity(c.doc_id)
            reason = (
                "insufficient_clearance"
                if sens in {"public", "internal", "confidential", "restricted"}
                and c.doc_id
                else "missing_acl_default_deny"
            )
            dropped.append(Dropped(c.doc_id, c.id, sens, reason))

    return Layer1Result(kept=kept, dropped=dropped)


# ----------------------------------------------------------------------------
# Layer 2 (M3): graph lineage check
# ----------------------------------------------------------------------------
@dataclass
class Redacted:
    """A chunk removed by Layer 2 because its lineage bridges to forbidden docs."""

    doc_id: str
    chunk_id: str
    sensitivity: str
    bridges: list[Bridge]

    @property
    def summary(self) -> str:
        parts = {f"{b.entity}->{b.target_doc}({b.target_sensitivity})" for b in self.bridges}
        return ", ".join(sorted(parts))


@dataclass
class Layer2Result:
    kept: list[Chunk]
    redacted: list[Redacted]


def layer2_graph_check(chunks: list[Chunk], role: str) -> Layer2Result:
    """Rule-based inference-leak check.

    A chunk may have passed Layer 1 (the role can see its document), yet that
    document can share a sensitive entity with a document the role CANNOT see.
    That shared entity is an inference bridge: answering from this chunk risks
    revealing restricted facts. We redact (drop) such chunks and record the path.
    """
    store = get_store()
    allowed = clearance_for(role)
    kept: list[Chunk] = []
    redacted: list[Redacted] = []

    for c in chunks:
        bridges = store.bridges_to_forbidden(c.doc_id, allowed)
        if bridges:
            redacted.append(Redacted(c.doc_id, c.id, c.sensitivity, bridges))
        else:
            kept.append(c)

    return Layer2Result(kept=kept, redacted=redacted)
