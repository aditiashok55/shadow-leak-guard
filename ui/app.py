"""shadow-leak-guard — interactive playground (Streamlit).

A visual way to *see* the leak and the defense layers. Pick a role, type any
question, toggle the three layers, and watch each stage's decision:

    retrieve  ->  Layer 1 (ACL)  ->  Layer 2 (graph)  ->  generate  ->  Layer 3 (guard)

Run:
    streamlit run ui/app.py

Everything is local — no API keys. Requires Ollama running + the Chroma index
built (`python src/ingest.py`).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st

# Make the flat `src/` modules importable (they use `from config import ...`).
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import ACL_PATH, ROLES_PATH  # noqa: E402
import graph as graph_mod  # noqa: E402
from ingest import ensure_ingested  # noqa: E402
from pipeline import run  # noqa: E402

st.set_page_config(page_title="shadow-leak-guard", page_icon="🛡️", layout="wide")


@st.cache_resource
def _bootstrap_index() -> int:
    """Build the Chroma index on first boot if empty (fresh cloud deploy)."""
    return ensure_ingested()


# Self-bootstrap so a fresh deploy needs no prebuilt index checked in.
try:
    _bootstrap_index()
except Exception as _e:  # pragma: no cover
    st.warning(f"Index bootstrap deferred: {_e}")


SENS_COLOR = {
    "public": "#2e7d32",       # green
    "internal": "#1565c0",     # blue
    "confidential": "#ef6c00", # orange
    "restricted": "#c62828",   # red
}


def badge(text: str, color: str) -> str:
    return (f"<span style='background:{color};color:white;padding:2px 8px;"
            f"border-radius:10px;font-size:0.75rem;font-weight:600'>{text}</span>")


@st.cache_data
def load_json(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text())


roles = load_json(str(ROLES_PATH))["roles"]
acl = load_json(str(ACL_PATH))

# ---------------------------------------------------------------- sidebar ----
st.sidebar.title("🛡️ shadow-leak-guard")
st.sidebar.caption("Permission-aware RAG leakage playground")

role = st.sidebar.selectbox(
    "Role (who is asking?)", list(roles.keys()), index=0,
    format_func=lambda r: f"{r} — {', '.join(roles[r]['clearance'])}",
)
st.sidebar.markdown(f"**Clearance:** " +
                    " ".join(badge(s, SENS_COLOR[s]) for s in roles[role]["clearance"]),
                    unsafe_allow_html=True)
st.sidebar.caption(roles[role]["description"])

st.sidebar.divider()
st.sidebar.subheader("Defense layers")
acl_filter = st.sidebar.toggle("Layer 1 — ACL pre-filter", value=False,
                               help="Deterministic default-deny. Drops chunks the role can't see.")
graph_check = st.sidebar.toggle("Layer 2 — graph lineage", value=False,
                                help="Redacts chunks that bridge to forbidden docs by inference.")
output_guard = st.sidebar.toggle("Layer 3 — output guard", value=False,
                                 help="LLM re-reads the final answer and blocks residual leaks.")

st.sidebar.divider()
backend = st.sidebar.radio("Graph backend (Layer 2)", ["networkx", "neo4j"], index=0,
                           help="Both give identical results. Neo4j needs the container + load_neo4j.py.")

# Apply backend choice (reset the cached store if it changed).
if os.environ.get("GRAPH_BACKEND") != backend:
    os.environ["GRAPH_BACKEND"] = backend
    graph_mod._STORE = None  # force rebuild on next get_store()

# ----------------------------------------------------------------- main ------
st.title("Can this role leak restricted data?")
st.markdown(
    "Type **any** question. With every layer **off**, semantic search can pull "
    "restricted documents into the answer. Turn the layers **on** and watch each "
    "stage filter the leak out."
)

# Role-aware suggestions. Each question is tagged with the sensitivity level it
# targets, so users see whether they're asking *within* their clearance (safe) or
# *probing above* it (the leak test). The ✅/🚨 prefix is computed per role below.
#   level = the highest sensitivity the question is really reaching for.
SUGGESTIONS = [
    ("public",       "What are the PTO and benefits policies?"),
    ("public",       "What's in the employee handbook about working hours?"),
    ("internal",     "What's on the engineering roadmap for this year?"),
    ("internal",     "Summarize the all-hands notes and internal budget."),
    ("confidential", "What does the financial forecast say about restructuring and severance?"),
    ("confidential", "What are the salary bands and merit pool for this cycle?"),
    ("restricted",   "What's the plan for next quarter's team changes?"),
    ("restricted",   "Summarize the reorg and anything about Project Atlas"),
    ("restricted",   "Tell me about the Northwind Analytics acquisition and layoffs."),
]

SENS_ORDER = ["public", "internal", "confidential", "restricted"]


def suggestion_label(level: str, role_clearance: list[str]) -> str:
    """Prefix a suggestion with whether this role is cleared for that level."""
    icon = "✅" if level in role_clearance else "🚨"
    tag = {"public": "public", "internal": "internal",
           "confidential": "confidential", "restricted": "restricted"}[level]
    status = "within clearance" if level in role_clearance else "ABOVE clearance — leak test"
    return f"{icon} [{tag}] {status}"


role_clearance = roles[role]["clearance"]

col_q, col_ex = st.columns([3, 2])
with col_ex:
    # Build labeled options tailored to the current role.
    options = ["(type your own)"]
    labels = {"(type your own)": "(type your own)"}
    for level, q in SUGGESTIONS:
        labels[q] = f"{suggestion_label(level, role_clearance)} — {q}"
        options.append(q)
    example = st.selectbox(
        f"Suggestions for **{role}** (✅ safe · 🚨 probes above clearance)",
        options, format_func=lambda o: labels[o],
    )
with col_q:
    default_q = "" if example == "(type your own)" else example
    query = st.text_input("Question", value=default_q or SUGGESTIONS[0][1])

# Little legend so the role/level relationship is explicit.
_cleared = " ".join(badge(s, SENS_COLOR[s]) for s in role_clearance)
_blocked = " ".join(badge(s, "#9e9e9e") for s in SENS_ORDER if s not in role_clearance)
st.markdown(
    f"<small><b>{role}</b> can see: {_cleared}" +
    (f" &nbsp;·&nbsp; cannot see: {_blocked}" if _blocked else " &nbsp;·&nbsp; (full access)") +
    "</small>",
    unsafe_allow_html=True,
)

go = st.button("▶ Run pipeline", type="primary", use_container_width=True)


def chunk_row(doc_id: str, sensitivity: str, extra: str = "") -> str:
    b = badge(sensitivity, SENS_COLOR.get(sensitivity, "#555"))
    return f"- `{doc_id}` {b} {extra}"


# Auto-run when any input changes (role, query, toggles, backend) OR button click.
# We cache the last result by an input signature so changing the role immediately
# re-runs and the output stays on screen instead of disappearing.
signature = (query, role, acl_filter, graph_check, output_guard, backend)
should_run = go or st.session_state.get("last_sig") != signature

if should_run and query.strip():
    flags_on = [n for n, v in [("L1", acl_filter), ("L2", graph_check),
                               ("L3", output_guard)] if v]
    st.caption(f"Role **{role}** · backend **{backend}** · layers: "
               f"{', '.join(flags_on) if flags_on else 'none (baseline)'}")

    with st.spinner("Running retrieval + local LLM…"):
        try:
            result = run(query, role, acl_filter=acl_filter,
                         graph_check=graph_check, output_guard=output_guard)
        except Exception as e:  # pragma: no cover
            st.error(f"Pipeline error: {e}\n\nIs Ollama running and the Chroma "
                     f"index built (`python src/ingest.py`)?")
            st.stop()
    st.session_state["last_sig"] = signature

    # ---- stage columns ----
    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("1 · Retrieved")
        st.caption("Top-k vector search — permission-blind (the leak source).")
        seen = []
        for c in result.kept_chunks:
            if c.doc_id not in seen:
                seen.append(c.doc_id)
                st.markdown(chunk_row(c.doc_id, c.sensitivity), unsafe_allow_html=True)
        for d in result.dropped:
            if d.doc_id not in seen:
                seen.append(d.doc_id)
                st.markdown(chunk_row(d.doc_id, d.sensitivity), unsafe_allow_html=True)
        for r in result.redacted:
            if r.doc_id not in seen:
                seen.append(r.doc_id)
                st.markdown(chunk_row(r.doc_id, r.sensitivity), unsafe_allow_html=True)

    with c2:
        st.subheader("2 · Filtered")
        if acl_filter and result.dropped:
            st.markdown("**Layer 1 dropped** (insufficient clearance):")
            for d in result.dropped:
                st.markdown(chunk_row(d.doc_id, d.sensitivity, f"· _{d.reason}_"),
                            unsafe_allow_html=True)
        if graph_check and result.redacted:
            st.markdown("**Layer 2 redacted** (inference bridge):")
            for r in result.redacted:
                st.markdown(chunk_row(r.doc_id, r.sensitivity), unsafe_allow_html=True)
                st.caption("↳ " + r.summary)
        if not (acl_filter and result.dropped) and not (graph_check and result.redacted):
            st.info("Nothing filtered at this stage.")

    with c3:
        st.subheader("3 · Allowed into LLM")
        kept_ids = []
        for c in result.kept_chunks:
            if c.doc_id not in kept_ids:
                kept_ids.append(c.doc_id)
                st.markdown(chunk_row(c.doc_id, c.sensitivity), unsafe_allow_html=True)
        if not kept_ids:
            st.warning("No chunks survived — pipeline blocks before generating.")

    st.divider()

    # ---- verdict + answer ----
    if result.blocked:
        st.error("🚫 **BLOCKED for this role**")
    else:
        st.success("✅ **Answer returned**")

    if result.guard is not None:
        verdict = "🔴 LEAK detected" if result.guard.leak else "🟢 clean"
        st.markdown(f"**Layer 3 output guard:** {verdict} — {result.guard.reason}")

    st.subheader("Final answer")
    st.markdown(f"> {result.answer}")
    note = result.access_note
    if note:
        st.info("🔒 **Why this answer is limited:** " + note)

    # ---- raw trace ----
    with st.expander("🔍 Raw trace spans (per step)"):
        st.json(result.trace.spans)

# --------------------------------------------------------- data browser ------
st.divider()
with st.expander("📂 Browse the data (roles, documents, ACL)"):
    st.markdown("**Roles & clearance**")
    st.table([
        {"role": r, "clearance": ", ".join(v["clearance"]), "note": v["description"]}
        for r, v in roles.items()
    ])
    st.markdown("**Documents & sensitivity** (what each role may open)")
    st.table([
        {"doc_id": d, "sensitivity": meta["sensitivity"],
         "allowed_roles": ", ".join(meta["allowed_roles"])}
        for d, meta in acl.items()
    ])
