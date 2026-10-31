# Diagrams (Mermaid)

GitHub renders these live. Screenshot them into the Medium article for polished
visuals, or export via the Mermaid Live Editor (https://mermaid.live).

## 1. The leak path

```mermaid
flowchart TD
    Q["🧑 intern: 'plan for next quarter's team changes?'"] --> R[Vector search · top-k · by MEANING]
    R --> A["hr_handbook<br/>public ✅"]
    R --> B["exec_ceo_memo<br/>RESTRICTED ⚠️"]
    R --> C["finance_budget<br/>internal ⚠️"]
    A --> G[LLM generates]
    B --> G
    C --> G
    G --> L["🔥 'eliminate ~30 roles,<br/>integrate Northwind acquisition'"]
    style B fill:#ffd6d6,stroke:#c00
    style C fill:#fff3cd,stroke:#d90
    style L fill:#ffe0e0,stroke:#c00,stroke-width:2px
```

## 2. Defense in depth (4 checkpoints)

```mermaid
flowchart TD
    Q[query + role] --> RET[Retrieve · vector search]
    RET --> L1{Layer 1<br/>ACL filter<br/>default deny}
    L1 -- dropped --> X1[(drop forbidden docs)]
    L1 -- allowed --> L2{Layer 2<br/>graph lineage}
    L2 -- bridge found --> X2[(redact inference leak)]
    L2 -- clean --> GEN[Generate · local LLM]
    GEN --> L3{Layer 3<br/>LLM output guard}
    L3 -- leak:true --> BLK[🚫 block + replace]
    L3 -- leak:false --> OUT[✅ answer]
    style L1 fill:#d6e8ff,stroke:#06c
    style L2 fill:#e6d6ff,stroke:#60c
    style L3 fill:#ffe6cc,stroke:#d60
    style BLK fill:#ffd6d6,stroke:#c00
    style OUT fill:#d6ffd6,stroke:#0a0
```

## 3. The inference leak (graph lineage)

```mermaid
flowchart LR
    subgraph seen["manager CAN see"]
        F["finance_forecast<br/>confidential"]
    end
    subgraph hidden["manager CANNOT see"]
        M["exec_ceo_memo<br/>RESTRICTED"]
        D["legal_ma_draft<br/>RESTRICTED"]
    end
    F -- mentions --> PA(["Project Atlas<br/>🔒 restricted entity"])
    M -- mentions --> PA
    D -- mentions --> PA
    PA --> BR{{🚨 BRIDGE → redact forecast}}
    style PA fill:#ffe0b3,stroke:#d60,stroke-width:2px
    style M fill:#ffd6d6,stroke:#c00
    style D fill:#ffd6d6,stroke:#c00
    style BR fill:#fff0f0,stroke:#c00,stroke-width:2px
```

## 4. Leak rate drops per layer

```mermaid
flowchart LR
    B["Baseline<br/>37.0%"] --> O1["+ Layer 1<br/>3.7%"]
    O1 --> O2["+ Layer 1+2<br/>0.0%"]
    O2 --> O3["+ Layer 1+2+3<br/>0.0%"]
    style B fill:#ffd6d6,stroke:#c00
    style O1 fill:#fff3cd,stroke:#d90
    style O2 fill:#d6ffd6,stroke:#0a0
    style O3 fill:#d6ffd6,stroke:#0a0
```

## 5. Leak rate bar chart

```mermaid
---
config:
  xyChart:
    width: 700
    height: 320
---
xychart-beta
    title "Leak rate by configuration (lower = better)"
    x-axis ["Baseline", "+L1", "+L1+2", "+L1+2+3"]
    y-axis "Leak rate (%)" 0 --> 40
    bar [37.0, 3.7, 0.0, 0.0]
```
