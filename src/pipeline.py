"""RAG pipeline for shadow-leak-guard.

Layers are toggled by flags so ablations are one-line changes:
  Layer 1 (acl_filter)   — M2: deterministic ACL pre-filter (default deny)
  Layer 2 (graph_check)  — M3: graph lineage check        (not yet implemented)
  Layer 3 (output_guard) — M4: LLM output guard           (not yet implemented)

With every layer off (baseline) restricted chunks leak into the answer.

Usage:
    python src/pipeline.py --role intern --query "What's the plan for next quarter's team changes?"
    python src/pipeline.py --role intern --acl-filter --query "..."   # Layer 1 on
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from guard import Dropped, Redacted, layer1_acl_filter, layer2_graph_check
from retrieve import Chunk, retrieve
from llm import generate
from trace import Trace

SYSTEM_PROMPT = (
    "You are an internal company assistant. Answer the user's question using ONLY "
    "the provided context. Be concise. If the context does not contain the answer, "
    "say you don't know."
)


@dataclass
class PipelineResult:
    answer: str
    kept_chunks: list[Chunk]
    dropped: list[Dropped] = field(default_factory=list)
    redacted: list[Redacted] = field(default_factory=list)
    blocked: bool = False
    trace: Trace = None  # type: ignore[assignment]


def build_prompt(query: str, chunks: list[Chunk]) -> str:
    context = "\n\n".join(f"[{c.doc_id}] {c.text}" for c in chunks)
    return f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer:"


def run(
    query: str,
    role: str,
    *,
    acl_filter: bool = False,   # Layer 1 (M2)
    graph_check: bool = False,  # Layer 2 (M3)
    output_guard: bool = False, # Layer 3 (M4)
) -> PipelineResult:
    trace = Trace()
    trace.span("query", role=role, query=query,
               flags={"acl_filter": acl_filter, "graph_check": graph_check,
                      "output_guard": output_guard})

    # --- Retrieve: pure top-k vector search (permission-agnostic) ---
    with trace.timed("retrieve") as t:
        chunks = retrieve(query)
        t.set(input_role=role, input_chunks=len(chunks),
              retrieved_docs=sorted({c.doc_id for c in chunks}))

    # --- Layer 1: deterministic ACL pre-filter (default deny) ---
    dropped: list[Dropped] = []
    if acl_filter:
        with trace.timed("layer1_acl") as t:
            result = layer1_acl_filter(chunks, role)
            chunks = result.kept
            dropped = result.dropped
            t.set(role=role, input_chunks=len(result.kept) + len(result.dropped),
                  kept=len(result.kept),
                  dropped=[{"doc_id": d.doc_id, "sensitivity": d.sensitivity,
                            "reason": d.reason} for d in result.dropped])
    else:
        trace.span("layer1_acl", enabled=False, note="baseline — no ACL enforcement")

    # --- Layer 2: graph lineage check (rule-based inference-leak catcher) ---
    redacted: list[Redacted] = []
    if graph_check:
        with trace.timed("layer2_graph") as t:
            result2 = layer2_graph_check(chunks, role)
            before = len(chunks)
            chunks = result2.kept
            redacted = result2.redacted
            t.set(role=role, input_chunks=before, kept=len(result2.kept),
                  redacted=[{"doc_id": r.doc_id, "sensitivity": r.sensitivity,
                             "bridges": [{"entity": b.entity,
                                          "target_doc": b.target_doc,
                                          "target_sensitivity": b.target_sensitivity,
                                          "hops": b.hops} for b in r.bridges]}
                            for r in result2.redacted])
    else:
        trace.span("layer2_graph", enabled=False, note="graph lineage check off")

    # Layer 3 is implemented in M4.

    if not chunks:
        trace.span("generate", skipped=True, reason="no_chunks_allowed")
        trace.span("final", blocked=True, answer_preview="")
        trace.save()
        return PipelineResult("I don't have information to answer that.",
                              chunks, dropped, redacted, True, trace)

    with trace.timed("generate") as t:
        answer = generate(SYSTEM_PROMPT, build_prompt(query, chunks))
        t.set(context_docs=sorted({c.doc_id for c in chunks}))

    trace.span("final", blocked=False, answer_preview=answer[:200])
    trace.save()
    return PipelineResult(answer, chunks, dropped, redacted, False, trace)


def main() -> None:
    ap = argparse.ArgumentParser(description="shadow-leak-guard baseline pipeline")
    ap.add_argument("--role", default="intern")
    ap.add_argument("--query", default="What's the plan for next quarter's team changes?")
    ap.add_argument("--acl-filter", action="store_true", help="enable Layer 1 (M2)")
    ap.add_argument("--graph-check", action="store_true", help="enable Layer 2 (M3)")
    args = ap.parse_args()

    result = run(args.query, args.role,
                 acl_filter=args.acl_filter, graph_check=args.graph_check)

    print("=" * 70)
    print(f"ROLE : {args.role}")
    print(f"QUERY: {args.query}")
    print(f"LAYER 1 (ACL)  : {'ON' if args.acl_filter else 'OFF (baseline)'}")
    print(f"LAYER 2 (GRAPH): {'ON' if args.graph_check else 'OFF'}")
    print("=" * 70)
    print("\nKEPT (doc_id : sensitivity):")
    for c in result.kept_chunks:
        print(f"  - {c.doc_id:32s} [{c.sensitivity}]")
    if result.dropped:
        print("\nDROPPED by Layer 1 (doc_id : sensitivity : reason):")
        for d in result.dropped:
            print(f"  - {d.doc_id:32s} [{d.sensitivity}]  {d.reason}")
    if result.redacted:
        print("\nREDACTED by Layer 2 (doc_id : sensitivity : inference bridges):")
        for r in result.redacted:
            print(f"  - {r.doc_id:32s} [{r.sensitivity}]  {r.summary}")
    print("\nANSWER:\n")
    print(result.answer)
    if result.blocked:
        print("\n[BLOCKED: no authorized context for this role]")
    print("\n" + "=" * 70)
    print(f"Trace saved: traces/{result.trace.run_id}.json")


if __name__ == "__main__":
    main()
