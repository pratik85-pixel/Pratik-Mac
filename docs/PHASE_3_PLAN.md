# Phase 3 — Split plan (A + B)

Phase 3 is intentionally split into two workstreams that can run **in parallel** after Phase 2, but **Part B** (boundaries + contract) makes **Part A** (PI) safer to reason about in production.

---

## Part A — Detection & physiology (PI + recovery Layer 2)

**Goal:** Add **vascular corroboration (PI)** and **recovery Layer 2** so stress and recovery events match physiology better when data quality allows, with graceful degradation when PI is missing.

### A.1 Stress events

- Ingest / compute **PI per 5‑min window** (or device-provided PI) into the same pipeline as RMSSD/HR.
- **Layer 3 gate:** PI drop vs personal baseline (or vs prior window) when `pi_quality` is acceptable.
- Preserve Phase 2 behavior when PI missing: do not block Layer 1+2 solely due to missing PI (policy: optional downgrade of **confidence** or **nudge** only).

### A.2 Recovery events

- **Layer 2 (new):** HR / arousal pattern check so “recovery” is not only RMSSD high (e.g. exclude sustained sympathetic HR pattern where appropriate).
- **Layer 3:** PI **rise** vs baseline (or complementary rule vs stress) when PI valid.
- Sleep aggregation may stay as today initially; daytime recovery windows get the new gates first.

### A.3 Shared

- Shared helpers for PI baseline, quality flags, and directional tests (stress vs recovery).
- Extend calibration or a rolling job for **PI_rest** / calm median.
- Tests: synthetic windows with known RMSSD/HR/PI combinations.

**Dependencies:** PPG or PI available on the mobile/BLE path and persisted per window.

---

## Part B — Scoring domain, readiness, boundaries, tests

**Goal:** **One canonical contract** for scores and time semantics so tracking, plan, coach, recap, and history do not diverge.

### B.1 Single domain service + contract

- One module (or service) owns **which fields** exist, **units**, **null rules**, and **version id** (`metrics_contract_id` or successor).
- **Consumers** (plan, coach, recap APIs) **read** that contract; they do not re-derive readiness from alternate formulas unless explicitly named (e.g. `plan_readiness`).

### B.2 Readiness reconciliation

- Either **one** user-facing readiness with a single formula, **or** two **explicitly named** fields (`tracking_readiness` vs `plan_readiness`) plus a documented mapping.
- Remove or quarantine **legacy** client-side readiness math so the app displays API truth.

### B.3 Feature inputs + cycle boundaries

- Standardize **morning reset**, **recap anchor day**, **day close**, and **“today”** in one place (module + tests).
- Define **feature snapshot** inputs for coach/plan (what is read at generation time vs materialized row).

### B.4 Deterministic test suites

- Golden tests for: sleep gaps, missing windows, partial days, missing PI/HR, timezone edges.
- Boundaries: same local date → same keys across tracking + recap + history builders.

---

## Execution order (recommended)

1. **B.3 boundaries** (small, unblocks consistency) — can start immediately.
2. **B.1 + B.2 contract + readiness** — reduces confusion while building A.
3. **A PI pipeline** — needs mobile/ingest work; parallelize with B where possible.
4. **A stress + recovery gates** — after PI on windows.
5. **B.4 tests** — expand as each piece lands.

---

## How you will know PI is integrated

| Signal | What to check |
|--------|----------------|
| **Data plane** | Every (or sampled) `BackgroundWindow` rows show **`perfusion_index` (or raw fields)** populated when the band sends PPG; logs show **non-null rate** by build. |
| **API / admin** | Debug or internal endpoint (or DB query) shows PI **present + in range** for valid stationary windows. |
| **Feature flag / build** | Version string e.g. `pi_pipeline_v1` in config or response proves the **new code path** is deployed. |

“Integrated” = **PI is stored and read** end-to-end, not only computed in a branch.

---

## How you will know PI is **working accurately**

Accuracy is **not** one number without labels. Use a **bundle of checks**:

### 1. **Plausibility & QC (sanity)**

- **Physiological direction:** On **labeled calm** segments, PI stable or consistent with literature; on **known motion**, PI flagged low-quality, not driving gates.
- **Correlation with existing signals:** When Layer 1 says stress, **PI should agree more often than chance** when quality is high (aggregate over many windows).

### 2. **Before/after Phase 2 vs Phase 3**

- **False positive rate** for stress **nudges** or **taggable events** drops (same users, same period type), without exploding false negatives.
- **Event merge/split stability:** Fewer “nonsense” flips when PI is present.

### 3. **Contrastive checks**

- **Stress vs recovery:** Distribution of PI (or ΔPI) should **separate** stress-tagged vs recovery-tagged windows better than RMSSD alone (offline analysis on exported data).

### 4. **Human ground truth (small)**

- **Spot-check** 50–100 windows: user or internal label “stress-like / not” vs model using PI gate; track **precision/recall** on that set.

### 5. **Ablation / shadow**

- Run **detector with PI off vs on** in shadow logging; compare disagreement rate and user complaints.

### 6. **Deterministic tests**

- Fixed synthetic series: **PI + RMSSD + HR** → **expected** gate outcome (pass/fail) locked in CI.

---

## Success criteria (short)

- **Integrated:** PI in DB + used in detector path + deployed build identifiable.
- **Accurate:** **Directional** agreement with physiology + **measurable** improvement vs PI-off on held-out checks + **stable** CI scenarios; **no** claim of “clinical accuracy” without a labeled study.

---

## Non-goals (unless you expand charter)

- Changing locked **four** score formulas without a separate approval.
- Full ML classifier replacing rule-based gates in Part A.

---

*Last updated: 2026-03-30 — aligns Phase 3 split (A/B) and PI validation expectations.*
