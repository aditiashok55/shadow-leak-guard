# M3 Evidence: Layer 2 — Graph Lineage Check

Reproduce with:
`python src/pipeline.py --role manager --acl-filter --graph-check --query "<q>"`

## The problem Layer 1 can't see
Layer 1 stops documents a role can't **open**. But two documents a role *can* open
may, together, reveal a secret. That is the **inference leak**.

Example: a `manager` is cleared for the **confidential** financial forecast. That
forecast names a codename — **Project Atlas** — which also appears in the
**restricted** CEO memo and M&A draft the manager cannot see.

## The graph model (behind a `GraphStore` interface, Neo4j-swappable)

```
 (Document {sensitivity}) ─MENTIONS→ (Entity {sensitivity})

 finance_forecast ──► "Project Atlas" ──► exec_ceo_memo
   [confidential]      [restricted entity]  [restricted]
        ▲                                        ▲
   manager CAN see                        manager CANNOT see
                      │
                      ▼
       🚨 BRIDGE within hop limit → redact the forecast chunk
```

**Rule:** redact an allowed chunk if its document mentions an entity that is
(a) labeled above the role's clearance **AND** (b) also appears in a document the
role cannot see.

## Layer 1 only vs Layer 1 + Layer 2 (manager)

Query: *"What does the financial forecast say about restructuring and severance?"*

```
LAYER 1 ONLY                           LAYER 1 + LAYER 2
────────────                           ─────────────────
KEPT:                                  KEPT: (none from the bridged docs)
  finance_forecast [confidential]
  hr_handbook      [public]            REDACTED by Layer 2:
  finance_budget   [internal]            finance_forecast_confidential
                                           Project Atlas → exec_ceo_memo (restricted)
ANSWER: describes the severance             Project Atlas → legal_ma_draft (restricted)
  charge and restructuring...  ⚠️
  (thread that leads to Atlas)         ANSWER: "I don't know..."  ✅ (inference leak closed)
```

## The design choice that prevents over-blocking
Entities carry their **own** sensitivity label. Generic overlap vocabulary
("team changes", "restructuring", "reorganization") is deliberately **not**
sensitive — it's the shared wording that makes search leak, but it isn't a secret.
Only distinctive entities (`Project Atlas`, `Northwind Analytics`, `acquisition`,
`layoffs`) trigger a redaction. Without this, Layer 2 redacts even `hr_handbook`.

## No false block for exec

```
ROLE : exec   L1 + L2 ON
Query: "What is Project Atlas and the acquisition plan?"
→ entities are within exec clearance → nothing redacted → answer allowed.  ✅
```

## Trace span

```json
{"step": "layer2_graph", "role": "manager", "input_chunks": 3, "kept": 2,
 "redacted": [
   {"doc_id": "finance_forecast_confidential", "sensitivity": "confidential",
    "bridges": [
      {"entity": "Project Atlas", "target_doc": "exec_ceo_memo_restricted",
       "target_sensitivity": "restricted", "hops": 2}
    ]}
 ], "latency_ms": 0.4}
```

## Takeaway
A rule-based, **~0.4 ms** graph check closes the inference leak the ACL filter
cannot see — taking leak rate from **3.7% → 0%** — without false-blocking cleared
roles or generic vocabulary.
