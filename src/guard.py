"""Guard layers for shadow-leak-guard.

Layer 1 (M2): deterministic ACL pre-filter. Default deny. No LLM involved.
Layer 2 (M3): graph lineage check (rule-based, NetworkX). No LLM involved.
Layer 3 (M4): LLM output guard.         (not yet implemented)

Design rule: deterministic controls first, LLM checks second.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from acl import clearance_for, doc_sensitivity, is_allowed
from graph import Bridge, get_store
from llm import generate
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


# ----------------------------------------------------------------------------
# Layer 3 (M4): LLM output guard  — SECOND-LINE detector, never the primary control
# ----------------------------------------------------------------------------

# Known secrets the model should never reveal to an under-cleared role. Derived
# from the restricted/confidential corpus; kept explicit so the detector prompt
# is grounded rather than relying on the model's judgement alone.
_SENSITIVE_HINTS = {
    "restricted": ["Project Atlas", "Northwind Analytics", "acquisition", "layoffs",
                   "eliminate", "redundant roles", "30 roles"],
    "confidential": ["severance", "retention bonuses", "salary bands", "merit pool",
                     "compensation bands"],
}

_GUARD_SYSTEM = (
    "You are a security output guard for an internal assistant. You are given a "
    "user's role, the sensitivity levels that role is cleared to see, and a draft "
    "answer. Decide whether the draft reveals any entity or fact the role should "
    "NOT see. Respond with STRICT JSON only: {\"leak\": true|false, \"reason\": "
    "\"short explanation\"}. No markdown, no extra text."
)


@dataclass
class Layer3Result:
    leak: bool
    reason: str
    raw: str


def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    # Strip ```json fences if present.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def layer3_output_guard(answer: str, role: str) -> Layer3Result:
    """LLM check on the final answer. Returns {leak, reason}.

    Treated as a *second-line* detector: deterministic Layers 1-2 are the real
    controls. This catches residual leaks they miss, but is never trusted alone.
    """
    cleared = clearance_for(role)
    # Collect forbidden hints = sensitivity levels the role is NOT cleared for.
    forbidden_hints: list[str] = []
    for level, hints in _SENSITIVE_HINTS.items():
        if level not in cleared:
            forbidden_hints.extend(hints)

    prompt = (
        f"Role: {role}\n"
        f"Cleared sensitivities: {cleared}\n"
        f"Examples of facts/entities this role must NOT see: {forbidden_hints}\n\n"
        f"Draft answer:\n\"\"\"\n{answer}\n\"\"\"\n\n"
        "Return STRICT JSON {\"leak\": bool, \"reason\": str}."
    )
    raw = generate(_GUARD_SYSTEM, prompt)
    parsed = _extract_json(raw)
    leak = bool(parsed.get("leak", False))
    reason = str(parsed.get("reason", "unparseable guard response"))
    return Layer3Result(leak=leak, reason=reason, raw=raw)
