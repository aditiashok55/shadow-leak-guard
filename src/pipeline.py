"""Baseline RAG pipeline for Milestone 1.

Layers 1-3 are defined by flags but are OFF in the baseline, so restricted
chunks leak into the answer. Later milestones flip these flags on.

Usage:
    python src/pipeline.py --role intern --query "What's the plan for next quarter's team changes?"
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

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
    dropped: list[str]
    blocked: bool
    trace: Trace


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

    with trace.timed("retrieve") as t:
        kept, dropped = retrieve(query, role, acl_filter=acl_filter)
        t.set(input_role=role, kept=len(kept), dropped=dropped,
              retrieved_docs=sorted({c.doc_id for c in kept}))

    # Layer 2 and Layer 3 are no-ops in the baseline (implemented in M3/M4).

    if not kept:
        trace.span("generate", skipped=True, reason="no_chunks_allowed")
        trace.save()
        return PipelineResult("I don't have information to answer that.", kept, dropped, True, trace)

    with trace.timed("generate") as t:
        answer = generate(SYSTEM_PROMPT, build_prompt(query, kept))
        t.set(context_docs=sorted({c.doc_id for c in kept}))

    trace.span("final", blocked=False, answer_preview=answer[:200])
    trace.save()
    return PipelineResult(answer, kept, dropped, False, trace)


def main() -> None:
    ap = argparse.ArgumentParser(description="shadow-leak-guard baseline pipeline")
    ap.add_argument("--role", default="intern")
    ap.add_argument("--query", default="What's the plan for next quarter's team changes?")
    ap.add_argument("--acl-filter", action="store_true", help="enable Layer 1 (M2)")
    args = ap.parse_args()

    result = run(args.query, args.role, acl_filter=args.acl_filter)

    print("=" * 70)
    print(f"ROLE : {args.role}")
    print(f"QUERY: {args.query}")
    print("=" * 70)
    print("\nRETRIEVED (doc_id : sensitivity):")
    for c in result.kept_chunks:
        print(f"  - {c.doc_id:32s} [{c.sensitivity}]")
    if result.dropped:
        print(f"\nDROPPED by ACL: {result.dropped}")
    print("\nANSWER:\n")
    print(result.answer)
    print("\n" + "=" * 70)
    print(f"Trace saved: traces/{result.trace.run_id}.json")


if __name__ == "__main__":
    main()
