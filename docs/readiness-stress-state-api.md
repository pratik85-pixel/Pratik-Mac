# Readiness API — Stress state & related contracts (Phases 2, 4–7)

Base path: same as deployed API (e.g. Railway). All authenticated tracking/plan routes expect header **`X-User-Id`** (user UUID string).

---

## `GET /tracking/stress-state`

**Phase 2–3 core.** Optional **Phase 7** query params.

### Query parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_cohort` | boolean | `false` | If `true`, response always includes `cohort`; `enabled` is true only when user set onboarding `compare_to_peers: true`. |

### Response 200 (`application/json`)

```json
{
  "stress_now_zone": "steady",
  "stress_now_index": 0.42,
  "stress_now_percent": 42.0,
  "trend": "stable",
  "confidence": "high",
  "reference_type": "time_of_day",
  "as_of": "2026-03-25T08:35:00+00:00",
  "rmssd_smoothed_ms": 36.2,
  "zone_cut_index_low": 0.22,
  "zone_cut_index_mid": 0.48,
  "zone_cut_index_high": 0.74,
  "morning_reference_ms": 38.0,
  "time_of_day_reference_ms": 35.5,
  "cohort": null
}
```

When `include_cohort=true`, `cohort` is always present:

```json
  "cohort": {
    "enabled": true,
    "band": "typical",
    "disclaimer": "Approximate peer context for your age group. Not medical advice; wide individual variation."
  }
```

If the user has not opted in, `"enabled": false` and `"band": null` (disclaimer string still populated for UI consistency).

`band` may be `below_typical` | `typical` | `above_typical` (placeholder heuristic).

### Field notes

- **`stress_now_zone`:** `calm` | `steady` | `activated` | `depleted` | `null` (insufficient recent data).  
- **`reference_type`:** `morning_avg` | `time_of_day` (blended median same DOW/hour when enough history).  
- **`morning_reference_ms` / `time_of_day_reference_ms`:** Echo for “details” sheet; `time_of_day` may be `null` if bucket too thin.

### Unchanged elsewhere

- **`GET /tracking/daily-summary`** — stress load, waking recovery, net balance, `rmssd_morning_avg`, etc. unchanged.

---

## `GET /tracking/morning-recap` (Phase 5)

Closes “yesterday” on first open (IST calendar date for `for_date`).

### Response 200

```json
{
  "for_date": "2026-03-24",
  "should_show": true,
  "acknowledged_for_date": false,
  "summary": {
    "stress_load_score": 55.0,
    "waking_recovery_score": 62.0,
    "net_balance": -3.2,
    "day_type": "yellow",
    "is_estimated": false,
    "is_partial_data": false,
    "sleep_recovery_area": 120.5,
    "closing_balance": -3.2
  }
}
```

- **`should_show`:** `false` if user already ack’d this `for_date` or no row for yesterday.  
- **`summary`:** `null` if no `DailyStressSummary` for that date.

---

## `POST /tracking/morning-recap/ack`

Body:

```json
{ "for_date": "2026-03-24" }
```

Marks recap dismissed for that date (cross-device). **200** `{ "ok": true, "for_date": "2026-03-24" }`.

---

## `GET /plan/home-status` (Phase 6)

Today’s plan headline for Home (IST day, aligned with `/plan/today`).

### Response 200

```json
{
  "has_plan": true,
  "plan_date": "2026-03-25",
  "anchor_intention": "ZenFlow session",
  "anchor_slug": "zenflow_session",
  "items_total": 5,
  "items_completed": 2,
  "adherence_pct": 40.0,
  "on_track": true,
  "day_type": "green"
}
```

- **`anchor_intention`:** First `must_do` item title, else first item.  
- **`on_track`:** Heuristic — e.g. adherence ≥ 50% or ≥ 1 completion when items exist.

---

## Phase 4 — Mobile (EAS) checklist

1. Home: call **`GET /tracking/stress-state`** on focus/interval; map zone → title from copy deck.  
2. Details sheet: `stress_now_percent`, references, disclaimer link.  
3. If `should_show` on **`GET /tracking/morning-recap`**, show card; on dismiss → **`POST .../ack`**.  
4. Home line: **`GET /plan/home-status`** for intention + on-track chip.  
5. Load today: continue using **`GET /tracking/daily-summary`** (`stress_load_score` vs budget — product framing).

---

## Config (env prefix `TRACKING_`)

See `config/tracking.py`: `STRESS_STATE_*`, including TOD blend and timezone.
