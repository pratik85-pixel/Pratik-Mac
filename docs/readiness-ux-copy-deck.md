# Readiness UX — Copy deck & IA (Phase 1)

**Purpose:** Legal/product sign-off on user-facing strings. **Not** clinical claims unless reviewed.

---

## Information architecture (tabs)

| Tab | Role |
|-----|------|
| **Home** | Stress **zone** (primary), **trend**, one line for **load today** *or* **plan on track**; details sheet for `%` and references. |
| **Plan** | Do’s / don’ts, adherence, anchor intention, tag nudges. |
| **Coach** | Realtime chat; context injected; does not replace Home explanations. |
| **History** | Past days, archived morning recap, profile, opt-in peer context. |

---

## Zone names (API → display)

| API `stress_now_zone` | Title | Subtitle hint |
|----------------------|--------|----------------|
| `calm` | Calm | Near or above your usual baseline right now. |
| `steady` | Steady | Typical day-to-day variation for you. |
| `activated` | Activated | Higher load than your usual right now — good time to use your plan. |
| `depleted` | Depleted | Much higher load than your usual — prioritize recovery and lighter demands. |

---

## Trend (`trend`)

| API value | Display | Microcopy |
|-----------|---------|-----------|
| `easing` | Easing | Recent signal is moving toward calmer vs a short while ago. |
| `stable` | Stable | Little short-term change vs the last check window. |
| `building` | Building | Recent signal suggests load is trending up. |
| `unclear` | Unclear | Not enough recent data or gaps — check back after wear. |

---

## Confidence (`confidence`)

| API value | Display | When |
|-----------|---------|------|
| `high` | High confidence | Several recent windows, small gaps. |
| `medium` | Medium | Some data; treat as directional. |
| `low` | Low | Band off, large gap, or stabilizing — don’t over-interpret. |

---

## Empty / error states

### No band data (no `stress_now_zone`)

- **Title:** Need a bit more wear  
- **Body:** Put your band on for about 10–15 minutes. We’ll estimate how loaded your system looks once we have clean readings.  
- **Secondary:** Last reading: {time} — optional if stale timestamp exists.

### Stabilizing (low confidence after gap)

- **Title:** Stabilizing…  
- **Body:** We’re updating your estimate after a break in wear.

### Morning recap unavailable (no yesterday summary)

- **Title:** Yesterday’s recap isn’t ready  
- **Body:** Wear the band through the day and night — we’ll close yesterday’s summary when we have enough data.

### Plan / intention missing

- **Title:** Today’s plan will appear here  
- **Body:** Open **Plan** after your morning read or when your coach sets items.

---

## Global disclaimer (“what this is not”)

**Short (footer / settings):**  
ZenFlow scores reflect patterns from your wearable and your personal baselines. They are **wellness signals**, not medical diagnosis or emergency detection.

**Long (Settings → How scoring works):**  
- Numbers describe **relative** load and recovery vs **your** history and references, not a universal “health grade.”  
- **Stress now** is a **momentary** estimate; **load today** is **cumulative** — they measure different things.  
- **Peer / age context** (if enabled) is **approximate** and varies widely between people — use it for curiosity, not comparison anxiety.  
- Contact a **qualified clinician** for medical concerns.

---

## Cohort / peer copy (opt-in only)

- **Toggle label:** Show approximate peer context (age group)  
- **Helper:** Wide individual differences — this is a rough band, not a ranking.  
- **Disclaimer (always with cohort block):** Based on approximate population patterns. Your body is unique; use this lightly.

---

## Sign-off

| Section | Owner | Date | Approved |
|---------|--------|------|----------|
| Zones + trends | Product | | ☐ |
| Disclaimers | Legal | | ☐ |
| Empty states | Product + Design | | ☐ |
