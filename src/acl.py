"""Load roles + ACL metadata and answer authorization questions.

Milestone 1 note: this module *stores* ACL metadata but the baseline pipeline
does NOT enforce it. Enforcement arrives in Milestone 2 (Layer 1).
"""
from __future__ import annotations

import json
from functools import lru_cache

from config import ACL_PATH, ROLES_PATH


@lru_cache(maxsize=1)
def load_roles() -> dict:
    return json.loads(ROLES_PATH.read_text())


@lru_cache(maxsize=1)
def load_acl() -> dict:
    return json.loads(ACL_PATH.read_text())


def clearance_for(role: str) -> list[str]:
    roles = load_roles()["roles"]
    if role not in roles:
        return []  # unknown role -> no clearance (default deny posture)
    return roles[role]["clearance"]


def doc_sensitivity(doc_id: str) -> str:
    """Return a doc's sensitivity, defaulting to 'restricted' if unknown (default deny)."""
    return load_acl().get(doc_id, {}).get("sensitivity", "restricted")


def doc_allowed_roles(doc_id: str) -> list[str]:
    return load_acl().get(doc_id, {}).get("allowed_roles", [])


def sensitivity_covered(role: str, sensitivity: str) -> bool:
    """True if the role's clearance covers a given sensitivity level."""
    return sensitivity in clearance_for(role)


def all_doc_ids() -> list[str]:
    return list(load_acl().keys())


def is_allowed(role: str, doc_id: str) -> bool:
    """Default-deny authorization check used by Layer 1 (M2)."""
    acl = load_acl()
    if doc_id not in acl:
        return False  # missing ACL -> blocked
    sensitivity = acl[doc_id]["sensitivity"]
    return sensitivity in clearance_for(role)
