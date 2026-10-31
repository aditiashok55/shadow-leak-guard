# M4 Evidence: Layer 3 — LLM Output Guard

Reproduce with:
`python src/pipeline.py --role <role> --output-guard --query "<q>"`

## The role of this layer
A **second-line detector** (`src/guard.py:layer3_output_guard`). The deterministic
Layers 1–2 are the real controls; Layer 3 reads the **final answer** and asks an
LLM whether it reveals anything the role shouldn't see. It returns strict JSON and,
on `leak: true`, blocks and replaces the answer.

> Design rule: never make the LLM the primary gate. It is the slowest and least
> reliable layer — a backstop, not a wall.

## It catches a leak when deterministic layers are OFF (intern)

```
ROLE : intern   L1: OFF   L2: OFF   L3: ON
QUERY: What's the plan for next quarter's team changes?

KEPT (unfiltered — restricted memo present):
  hr_handbook, exec_ceo_memo_restricted, finance_budget_internal

LAYER 3 verdict: LEAK — "reveals Project Atlas, Northwind Analytics,
  acquisition, eliminate, redundant roles, 30 roles, merit pool..."

ANSWER: [BLOCKED by output guard: this answer may reveal information
         your role is not cleared to see.]   ✅ caught
```

## It passes safe answers (no false positive)

```
ROLE : intern   L1 + L2 + L3 ON  (full stack)
QUERY: What's the plan for next quarter's team changes?

KEPT: hr_handbook, hr_handbook   (restricted already dropped by L1)
LAYER 3 verdict: clean — "No sensitive information is revealed."

ANSWER: "The plan ... is collaborative: managers submit proposals,
         HR reviews them, and employees are notified..."   ✅ allowed
```

## It respects clearance (exec)

```
ROLE : exec   L1 + L2 + L3 ON
LAYER 3 verdict: clean — "The role is cleared for 'restricted', so it may
  see the acquisition and team changes."

ANSWER: full CEO-memo detail.   ✅ allowed (exec is authorized)
```

## Output contract

```json
{ "leak": true,
  "reason": "Draft reveals Project Atlas and the acquisition the intern must not see." }
```

## Trace span

```json
{"step": "layer3_output", "role": "intern", "leak": true,
 "reason": "...", "latency_ms": 820.5}
```

## Takeaway
Layer 3 **catches** what the deterministic layers miss, **passes** legitimately
safe answers, and **respects** clearance for authorized roles. The cost is real —
~800 ms for the extra LLM call vs ~0.5 ms for L1/L2 — which is exactly why it is a
backstop, not the front line.
