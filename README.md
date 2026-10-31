# shadow-leak-guard

Permission-aware RAG with a leakage red-team. We build a plain RAG pipeline,
show that **semantic search leaks restricted documents past folder permissions**,
then add layered enforcement and measure how much each layer reduces leakage.

> Folder permissions fail in RAG. Semantic search can retrieve restricted chunks.
> This project builds layered enforcement and measures each layer's effect.

## Status

- [x] **M1 — Synthetic corpus + baseline leak demo** (current)
- [ ] M2 — Layer 1: ACL pre-filter
- [ ] M3 — Layer 2: graph lineage check
- [ ] M4 — Layer 3: output guard
- [ ] M5 — Red-team eval + ablation table

## Architecture

```
user query + role
      │
      ▼
[Retrieve]   vector search (top-k)                 ← ChromaDB + Ollama embeddings
      │
      ▼
[Layer 1]    ACL pre-filter (default deny)         ← M2
      │
      ▼
[Layer 2]    Graph lineage check (NetworkX)        ← M3
      │
      ▼
[Generate]   local LLM over allowed chunks         ← Ollama
      │
      ▼
[Layer 3]    Output guard (LLM leak detector)      ← M4
      │
      ▼
answer or block  ──►  JSON trace per step (traces/)
```

## Roles & sensitivity

| Role | Clearance |
|---|---|
| intern | public |
| employee | public, internal |
| manager | public, internal, confidential |
| exec | public, internal, confidential, restricted |

Restricted documents in the corpus: `hr_salary_bands`, `legal_ma_draft_restricted`,
`exec_ceo_memo_restricted`. These share vocabulary ("next quarter's team changes",
"reorganization", "restructuring") with public docs so semantic search pulls them.

## Prerequisites

1. [Ollama](https://ollama.com) running locally with the models pulled:
   ```bash
   ollama pull nomic-embed-text
   ollama pull llama3.2
   ```
2. Python 3.11+ and the requirements:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Reproduce the leak (M1)

```bash
./demo_leak.sh
```

This ingests the corpus (ACL metadata stored but **not enforced**) and runs an
intern's benign question — `"What's the plan for next quarter's team changes?"` —
through the baseline RAG. The restricted CEO memo / M&A draft are retrieved by
semantic similarity and leak into the answer.

Run manually:

```bash
python src/ingest.py
python src/pipeline.py --role intern --query "What's the plan for next quarter's team changes?"
# Preview the M2 fix early:
python src/pipeline.py --role intern --acl-filter --query "What's the plan for next quarter's team changes?"
```

Every run writes a step-by-step trace to `traces/<run_id>.json`.

## Layout

```
shadow-leak-guard/
├── data/
│   ├── docs/     # 15 synthetic markdown documents
│   ├── roles.json
│   └── acl.json
├── src/
│   ├── config.py     # paths, models, knobs
│   ├── acl.py        # roles + ACL authorization (default deny)
│   ├── llm.py        # Ollama embeddings + chat (temperature 0)
│   ├── ingest.py     # chunk → embed → store with ACL metadata
│   ├── retrieve.py   # vector search (+ optional ACL filter)
│   ├── pipeline.py   # ties layers together via flags
│   └── trace.py      # JSON span logging
├── demo_leak.sh
└── requirements.txt
```

## Design rules

- Deterministic controls first, LLM checks second
- Default deny (missing ACL ⇒ blocked)
- Every layer emits a trace span
- Layers toggled by flags for one-line ablations
- Temperature 0 + fixed seed for reproducibility
- Document text is treated as untrusted input
