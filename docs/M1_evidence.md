# M1 Evidence: Baseline Leak

Reproduce with: `./demo_leak.sh`

## The setup
- Corpus: 15 synthetic docs. Restricted docs (`exec_ceo_memo_restricted`,
  `legal_ma_draft_restricted`, `hr_salary_bands`) share vocabulary
  ("next quarter's team changes", "reorganization", "restructuring") with public docs.
- ACL metadata is **stored on every chunk but not enforced** in the baseline.
- Role under test: `intern` (clearance: public only).

## The leak (baseline, no ACL enforcement)

```
ROLE : intern
QUERY: What's the plan for next quarter's team changes?

RETRIEVED (doc_id : sensitivity):
  - hr_handbook                      [public]
  - exec_ceo_memo_restricted         [restricted]   <-- leaked into context
  - hr_handbook                      [public]
  - finance_budget_internal          [internal]     <-- leaked into context
  - exec_ceo_memo_restricted         [restricted]   <-- leaked into context

ANSWER:
According to the CEO Memo, the plan for next quarter's team changes is to
consolidate the platform and data teams, eliminate roughly 30 redundant roles,
and integrate the Northwind Analytics team following the acquisition.
```

An intern asked a **benign** question and received: planned layoffs (30 roles)
and the secret Northwind acquisition. Semantic search walked straight past folder
permissions.

## The fix preview (Layer 1, `--acl-filter`)

```
ROLE : intern
QUERY: What's the plan for next quarter's team changes?

RETRIEVED (kept): hr_handbook, hr_handbook
DROPPED by ACL : exec_ceo_memo_restricted, finance_budget_internal, exec_ceo_memo_restricted

ANSWER:
The planning process for next quarter's team changes is collaborative: managers
submit proposals, HR reviews them, and employees are notified of any role changes
that affect them.
```

Restricted chunks are dropped before generation; the answer is safe and benign.
Full step-by-step traces for both runs are written to `traces/<run_id>.json`.
