# shadow-leak-guard

Permission-aware RAG with a leakage red-team. We build a plain RAG pipeline,
show that **semantic search leaks restricted documents past folder permissions**,
then add layered enforcement and measure how much each layer reduces leakage.

> Folder permissions fail in RAG. Semantic search can retrieve restricted chunks.
> This project builds layered enforcement and measures each layer's effect.

## Status

- [x] **M1 — Synthetic corpus + baseline leak demo**
- [x] **M2 — Layer 1: ACL pre-filter**
- [x] **M3 — Layer 2: graph lineage check**
- [x] **M4 — Layer 3: output guard**
- [x] **M5 — Red-team eval + ablation table** (current)

## Results — red-team ablation

27 adversarial queries across 6 categories (direct, paraphrase, multi-hop
inference, role-escalation, prompt-injection, benign/authorized) run under four
configurations. A **leak** = a forbidden fact appears in a substantive answer (a
refusal that merely names the topic it declines does not count). A **false-block**
= an answerable case that was wrongly refused.

| Config | Leak rate | False-block rate | Avg latency |
|---|---|---|---|
| Baseline | 37.0% | 0.0% | 2272 ms |
| + Layer 1 | 3.7% | 12.5% | 1680 ms |
| + Layer 1+2 | 0.0% | 18.8% | 1500 ms |
| + Layer 1+2+3 | 0.0% | 18.8% | 3376 ms |

Reproduce: `python evals/run_eval.py` (writes `evals/results.json`).

**Reading the table**
- **Layer 1 (ACL pre-filter)** does the heavy lifting: 37% → 3.7% leak for a
  deterministic, sub-millisecond control.
- **Layer 2 (graph lineage)** closes the residual inference leak to **0%** by
  catching cross-document entity bridges (e.g. a confidential forecast naming
  `Project Atlas`).
- **Layer 3 (output guard)** holds leak at 0% as a second-line detector; it adds
  latency (an extra LLM call) without false-blocking beyond Layer 2.
- **False-blocks are the honest tradeoff.** Of the 3: two are the small local
  model conservatively answering "I don't know" from valid public context (model
  caution, not the guard), and one is Layer 2 legitimately redacting a
  `Project Atlas`-bridged forecast — the expected precision cost of inference
  defense.

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

## Layer 1 — ACL pre-filter (M2)

A deterministic, **default-deny** control that runs after retrieval and before
generation (`src/guard.py:layer1_acl_filter`). For each retrieved chunk it checks
the role's clearance against the doc's sensitivity; anything not explicitly
allowed is dropped with a machine-readable reason
(`insufficient_clearance`, `missing_acl_default_deny`, `unknown_role_default_deny`).

```bash
# intern, Layer 1 ON -> restricted CEO memo is dropped, answer is benign
python src/pipeline.py --role intern --acl-filter --query "What's the plan for next quarter's team changes?"

# exec, Layer 1 ON -> full clearance, legitimately sees restricted content (no false block)
python src/pipeline.py --role exec --acl-filter --query "What's the plan for next quarter's team changes?"
```

Each run emits a `layer1_acl` trace span:

```json
{"step": "layer1_acl", "role": "intern", "input_chunks": 5, "kept": 2,
 "dropped": [{"doc_id": "exec_ceo_memo_restricted", "sensitivity": "restricted",
              "reason": "insufficient_clearance"}],
 "latency_ms": 0.61}
```

## Layer 2 — graph lineage check (M3)

Layer 1 stops documents the role cannot open. But a document a role *can* open may
share a secret with one it cannot — revealing restricted facts by **inference**.
Layer 2 (`src/graph.py` + `src/guard.py:layer2_graph_check`) is a rule-based,
no-LLM check for that leak.

Model (behind a `GraphStore` interface so Neo4j can swap in later):

```
(Document {sensitivity}) -[:MENTIONS]-> (Entity {sensitivity})
```

Distinctive secrets — `Project Atlas`, `Northwind Analytics`, `acquisition`,
`layoffs` — are labeled `restricted`. Generic overlap vocabulary (`team changes`,
`restructuring`, `reorganization`) is deliberately **not** sensitive: it is the
shared wording that makes semantic search leak, but it is not itself a secret, so
it never causes a false block.

**Rule:** an allowed chunk is redacted if its document mentions an entity that is
(a) labeled above the role's clearance **and** (b) also appears in a document the
role cannot see — a bridge within `hop_limit` hops (`doc → entity → forbidden_doc`).

```bash
# manager can open the CONFIDENTIAL forecast, but it names "Project Atlas",
# which bridges to the RESTRICTED M&A draft / CEO memo -> Layer 2 redacts it
python src/pipeline.py --role manager --acl-filter --graph-check \
  --query "What does the financial forecast say about restructuring and severance?"

# exec: same entities are within clearance -> nothing redacted (no false block)
python src/pipeline.py --role exec --acl-filter --graph-check \
  --query "What is Project Atlas and the acquisition plan?"
```

`layer2_graph` trace span records each redaction with its bridge path:

```json
{"step": "layer2_graph", "role": "manager", "input_chunks": 3, "kept": 2,
 "redacted": [{"doc_id": "finance_forecast_confidential", "sensitivity": "confidential",
   "bridges": [{"entity": "Project Atlas", "target_doc": "exec_ceo_memo_restricted",
                "target_sensitivity": "restricted", "hops": 2}]}],
 "latency_ms": 0.4}
```

## Layer 3 — output guard (M4)

An **LLM** check on the final answer (`src/guard.py:layer3_output_guard`). It is a
deliberate **second-line detector**: the deterministic Layers 1–2 are the real
controls; this catches residual leaks they miss but is never trusted as the primary
gate. It receives the role, its cleared sensitivities, and known forbidden hints,
then returns strict JSON `{"leak": bool, "reason": str}`. On `leak: true` the
pipeline blocks and replaces the answer.

```bash
# Layer 3 ONLY, deterministic layers OFF -> it still catches the baseline leak
python src/pipeline.py --role intern --output-guard \
  --query "What's the plan for next quarter's team changes?"

# Full stack: L1 + L2 produce a safe answer, L3 confirms it is clean (no false block)
python src/pipeline.py --role intern --acl-filter --graph-check --output-guard \
  --query "What's the plan for next quarter's team changes?"
```

`layer3_output` trace span:

```json
{"step": "layer3_output", "role": "intern", "leak": true,
 "reason": "Draft reveals Project Atlas and the acquisition the intern must not see.",
 "latency_ms": 820.5}
```

## Layout

```
shadow-leak-guard/
├── data/
│   ├── docs/     # 16 synthetic markdown documents (incl. a prompt-injection doc)
│   ├── roles.json
│   ├── acl.json
│   └── entities.json  # hand-labeled entities + entity sensitivity (Layer 2)
├── src/
│   ├── config.py     # paths, models, knobs
│   ├── acl.py        # roles + ACL authorization (default deny)
│   ├── llm.py        # Ollama embeddings + chat (temperature 0)
│   ├── ingest.py     # chunk → embed → store with ACL metadata
│   ├── retrieve.py   # pure top-k vector search (permission-agnostic)
│   ├── graph.py      # GraphStore interface + NetworkX lineage graph (Layer 2)
│   ├── guard.py      # Layer 1 ACL + Layer 2 graph check + Layer 3 output guard
│   ├── pipeline.py   # ties layers together via flags
│   └── trace.py      # JSON span logging
├── evals/
│   ├── queries.json  # 27 adversarial red-team cases
│   ├── run_eval.py   # runs all 4 configs, prints the ablation table
│   └── results.json  # latest eval output
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
