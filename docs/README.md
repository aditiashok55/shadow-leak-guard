# Evidence Log

Milestone-by-milestone proof, each reproducible with one command.

| Milestone | Layer | Evidence | Headline result |
|---|---|---|---|
| M1 | Baseline leak | [M1_evidence.md](M1_evidence.md) | Intern leaks the CEO memo (30 layoffs + Northwind) |
| M2 | Layer 1 · ACL pre-filter | [M2_evidence.md](M2_evidence.md) | ~0.6 ms deterministic check; leak 37% → 3.7% |
| M3 | Layer 2 · graph lineage | [M3_evidence.md](M3_evidence.md) | Catches inference leak; 3.7% → 0% |
| M4 | Layer 3 · output guard | [M4_evidence.md](M4_evidence.md) | LLM second-line detector; holds 0% |
| M5 | Red-team eval | [M5_evidence.md](M5_evidence.md) | 27 cases, 4 configs; full ablation table |

See also the write-up in [`../article/`](../article/) and live diagrams in
[`../article/diagrams.md`](../article/diagrams.md).

## Phase 2 — production upgrades

| Upgrade | What | Status |
|---|---|---|
| U1 | **Langfuse tracing** — one span per layer (role, dropped chunks, tokens, latency); graceful no-op without keys | ✅ done |
| U2 | **Neo4j graph backend** — `Neo4jGraphStore` behind the same `GraphStore` interface; identical leak curve on both backends | ✅ done |
| U4 | **CI evals** — GitHub Action runs `run_eval.py`, fails on leak-rate regression | ⬜ planned |

Both U1 and U2 are **optional at runtime**: with no keys and the default
`GRAPH_BACKEND=networkx`, the pipeline runs exactly as in Phase 1. See the main
[`../README.md`](../README.md) "Observability" and "Graph backend — Neo4j" sections
for setup and example outputs.
