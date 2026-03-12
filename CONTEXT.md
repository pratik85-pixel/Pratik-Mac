# ZenFlow Verity — Project Context

**Last updated:** 11 March 2026
**Hardware:** Polar Verity Sense (optical armband)
**Status:** DEPLOYED & WORKING — API live on Railway, Android APK installed on test phone
**Parent project:** ZenFlow_project (H10 chest strap, running and stable — do not touch)

---

## Current System State (11 March 2026)

### What is working right now
- Railway API: `https://api-production-8195d.up.railway.app` — LIVE and healthy
- Railway Postgres: provisioned and connected (`postgres-ciqd.railway.internal:5432`)
- All 3 Alembic migrations applied: initial schema, psychological profile tables, unified user profile + user facts tables
- Android APK v5 installed on test phone (device: `JJCE6H4XJNXS6L8D`, package: `com.zenflow.verity`)
- Onboarding → home screen flow working end-to-end

### Key credentials
| Item | Value |
|---|---|
| Railway API URL | `https://api-production-8195d.up.railway.app` |
| Railway project ID | `52409a46-4797-4027-b17a-e25cfb8fd62c` |
| Postgres internal URL | `postgresql://postgres:VaebpXWINRSXJrVlakRrqSBDeehOeEEh@postgres-ciqd.railway.internal:5432/railway` |
| Postgres service name | `postgres-ciqd` (NEW — replaced crashed original) |
| EAS project | `@pratik85/zenflow-verity` (ID: `bab74a16-9052-43bd-9c2a-cc33fc667a02`) |
| EAS token | `NkUqALgfgbtl9bqLG8UW8OlhSn7QSW2MLHs_6Tyn` |
| Last APK build ID | `ee67c4cf-1388-4dcd-a3de-4a326a125b66` |
| Last APK artifact | `https://expo.dev/artifacts/eas/vrtQo2HhVUpJzFYH4J79cq.apk` |
| Test phone adb ID | `JJCE6H4XJNXS6L8D` |
| adb path | `/Users/pratikbarman/Library/Android/sdk/platform-tools/adb` |

---

## Repository Structure

**Two separate repos:**

### `/Users/pratikbarman/Desktop/ZenFlow_Verity` — FastAPI backend
- `api/config.py` — Pydantic settings; `DATABASE_URL`/`DATABASE_SYNC_URL` validators strip `postgresql://` → asyncpg/psycopg2 prefixes
- `api/main.py` — FastAPI entrypoint
- `api/routers/` — route handlers (tracking, coach, profile, etc.)
- `api/services/` — business logic
- `api/db/` — SQLAlchemy async engine
- `alembic/` — 3 migrations applied
- `Dockerfile`, `railway.toml`, `start.sh` (runs `alembic upgrade head` then `uvicorn`), `requirements.txt`
- `processing/`, `model/`, `archetypes/`, `coach/`, `outcomes/`, `tracking/`, `sessions/`, `psych/`, `profile/`, `tagging/`, `jobs/`, `scripts/`

### `/Users/pratikbarman/Desktop/ZenFlowVerity` — React Native / Expo frontend
- `App.tsx` — bootstrap: saves API base, calls `initClient` (**must** be awaited), loads `userId`
- `src/api/client.ts` — axios instance; `initClient()`, `setUserId()`, `getClient()`
- `src/api/endpoints.ts` — all API call functions (`getToday`, `updateHabits`, `rebuildProfile`, etc.)
- `src/screens/HomeScreen.tsx` — calls `getToday()` on focus; shows error state if API fails
- `src/screens/onboarding/Step8Name.tsx` — final onboarding step: generates UUID, calls `saveUser`, navigates to Main
- `src/store/auth.ts` — AsyncStorage wrappers: `saveUser`, `getUser`, `saveApiBase`, `getApiBase`
- `src/navigation/` — `AppNavigator`, `OnboardingNavigator`
- `src/components/` — `ScreenWrapper`, `ScoreCard`, `DayTypeBadge`, `EmptyState`, etc.
- `eas.json` — preview profile: `buildType=apk`, `EXPO_PUBLIC_API_URL=https://api-production-8195d.up.railway.app`

---

## Git History

### ZenFlowVerity (frontend)
```
f7b0e892  fix: treat 404 as empty state, not server error on HomeScreen  ← LATEST
978dbeea  fix: remove hardcoded local API URL from onboarding that overwrote Railway URL
f770359b  fix: await initClient on startup + fix stale WiFi error message
1d84be89  fix: add splash image + adaptive icon foreground to fix Gradle build
1be05c56  fix: add .gitignore, remove node_modules from tracking
9aec5a52  Initial commit
```

### ZenFlow_Verity (backend)
```
879878c  start.sh: migrations + uvicorn, fix Dockerfile CMD  ← LATEST
dc9f4d2  Remove Procfile startCommand override, simplify railway.toml
b87cf23  Minimal Dockerfile: direct uvicorn, skip migrations
98505e2  Make migrations non-fatal so uvicorn starts regardless
```

---

## Key Architecture & Gotchas

### API client bootstrap (`App.tsx`)
```tsx
const DEV_API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';
await saveApiBase(DEV_API_BASE);   // persists to AsyncStorage
await initClient(DEV_API_BASE);    // builds axios instance — MUST be awaited
```
`EXPO_PUBLIC_API_URL` is baked in at EAS build time from `eas.json preview.env`.

### User ID flow
- `uuidv4()` generated in `Step8Name.tsx` at end of onboarding
- Stored in AsyncStorage under key `user_id`
- Loaded in `App.tsx` bootstrap → `setUserId(stored.userId)`
- Injected as `X-User-Id` header on every request via axios interceptor
- All `/tracking/*` endpoints require a valid UUID in `X-User-Id` — returns `422` if missing/invalid

### Root cause of "Can't reach server" (FIXED — commit `978dbeea`)
`Step8Name.tsx` had three lines that ran at the end of onboarding:
```ts
const apiBase = 'http://192.168.1.33:8000';  // hardcoded old laptop IP
initClient(apiBase);       // overwrote Railway URL in memory
await saveApiBase(apiBase); // persisted dead URL to AsyncStorage permanently
```
Every user who completed onboarding was stuck pointing at a dead local IP.
**Fix:** removed all three lines. `App.tsx` already initialised the client with the Railway URL before onboarding started.

### `api/config.py` DATABASE_URL validators
- `_fix_async_url`: `postgresql://` → `postgresql+asyncpg://` (used by SQLAlchemy async engine)
- `_fix_sync_url`: `postgresql://` → `postgresql+psycopg2://` (used only by Alembic migrations)
- asyncpg ignores `?sslmode=require` in URL — do not add it. Internal Railway networking doesn't need SSL.

### Railway Postgres history
- Original Postgres crashed in a loop ("Stopping Container" immediately after "ready to accept connections")
- `railway redeploy` did not fix it — likely corrupted volume
- **Solution:** deleted via Railway dashboard, provisioned new service (`postgres-ciqd`)
- Set both `DATABASE_URL` and `DATABASE_SYNC_URL` on the `api` service to the new internal URL
- 3 migrations ran cleanly

---

## Issue History (all resolved)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | EAS build ERRORED | node_modules committed to git | Added `.gitignore`, removed from tracking |
| 2 | EAS build ERRORED | Missing `splashscreen_logo` drawable | Added `splash.image` + `adaptiveIcon.foregroundImage` to `app.json` |
| 3 | App "can't reach server" | `initClient` not awaited in `App.tsx` | Added `await` |
| 4 | asyncpg `TimeoutError` / Postgres crash loop | Corrupted Railway Postgres volume | Deleted, provisioned new `postgres-ciqd` service |
| 5 | App "can't reach server" after onboarding | `Step8Name.tsx` hardcoded local IP, overwrote Railway URL | Removed 3 lines from `Step8Name.tsx` |
| 6 | App shows "Can't reach server" on home screen for new users | `/tracking/daily-summary` returns 404 when no sessions exist; axios throws on non-2xx → `HomeScreen` treated it as network error | Check `e.response.status === 404` in `load()`, set `noData=true` instead of `error=true`; show "Nothing here yet" empty state |

---

## Useful Commands

```bash
# Check API health
curl https://api-production-8195d.up.railway.app/health

# Test DB-dependent endpoint (replace UUID with a real one from the app)
curl https://api-production-8195d.up.railway.app/tracking/daily-summary \
  -H "x-user-id: 00000000-0000-0000-0000-000000000001"

# Railway
cd /Users/pratikbarman/Desktop/ZenFlow_Verity
railway logs --service api
railway logs --service Postgres
railway variables --service api
railway redeploy --service api --yes

# Build new APK
export PATH="$HOME/.npm-global/bin:$PATH" EXPO_TOKEN="NkUqALgfgbtl9bqLG8UW8OlhSn7QSW2MLHs_6Tyn"
cd /Users/pratikbarman/Desktop/ZenFlowVerity
eas build --platform android --profile preview --non-interactive

# Install APK to phone
/Users/pratikbarman/Library/Android/sdk/platform-tools/adb install -r ~/Downloads/ZenFlow-vX.apk
```

---

## What to Work on Next

App and API are live and working. Next priorities are the actual HRV/physiology features:

1. **Polar BLE SDK integration** — stream PPI + PPG raw from Verity Sense into the app
2. **Processing pipeline** — PPI → RMSSD, RSA coherence scoring (Verity no-accel architecture)
3. **Session engine** — guided breathing with real-time coherence feedback (visual ring)
4. **Background HRV monitoring** — passive stress arc tracking, nudge triggers
5. **Baseline week** — 7-day onboarding measurement protocol

**Do not start algorithm work until real PPI signal quality is validated from the band.**

---

## Original Context (pre-development)

---

## Why This Is a Separate Project

ZenFlow_project (H10) is running perfectly with real users. Its calibration/confidence scoring system has been empirically tuned through user sessions — thresholds like the 0.3 r-value, 80-point lock threshold, and 45s force-lock are not theoretical; they came from iterative real-world testing. Merging Verity development into that codebase risks silent regressions that only show up during live sessions, which cannot be regression-tested in CI because the product is evaluated by how users feel.

**This project is a clean fork — not a config variant.**

---

## What Polar Verity Sense Provides (SDK Streams)

| Stream | Rate | Notes |
|---|---|---|
| PPI (PPG peak-to-peak) | Event-driven | RR equivalent, ~5–8ms jitter at rest vs ~1ms ECG |
| PPG raw | 135Hz, 3-channel | Red, IR, Green optical signal — the big unlock |
| ACC | 52Hz, 3-axis | Arm-worn — NOT useful for breath detection (no chest expansion) |
| Gyroscope | 52Hz | H10 doesn't have this — useful for movement/restlessness scoring |
| HR | 1Hz | Standard optical HR |

**Key difference from H10:**
- No ECG → no EDR (ECG-Derived Respiration)
- No chest ACC → breath MUST be inferred from RSA oscillation in RR, or from PAV (Pulse Amplitude Variation in raw PPG) — this is an open research question to validate with real data first
- PPG raw 3-channel → enables Perfusion Index, SpO2 trend, PAV breath detection
- Gyroscope is new capability H10 doesn't have

---

## Why the H10 Algorithm Doesn't Port Directly

The H10 confidence/calibration system is fundamentally accel-first:

```python
# H10 bridge.py — line 2163
accel_score = CONF_ACCEL_POINTS  # 50 pts ALWAYS — hardcoded reference
locked_bpm = accel_mean           # BPM is derived from accel, not RSA
```

For Verity (no chest ACC):
- Max achievable score = 50 pts (RSA only) → never reaches the 80-point lock threshold
- Every session becomes a force-lock at 45s → calibration quality undefined
- `locked_bpm` has no reference signal → must be rebuilt using EDR autocorrelation or RSA Lomb-Scargle peak as primary

**What needs to be rebuilt in bridge.py for Verity:**
1. EDR re-enabled and promoted to primary reference signal (computed from PPI, not ECG — validity to be tested)
2. New scoring: `accel_score → 0`, `CONF_RSA_HIGH_R_POINTS → 100`, `CONF_LOCK_THRESHOLD → 50`
3. `locked_bpm` derivation from EDR or RSA peak instead of `accel_mean`
4. PAV breath detection as optional third signal (experimental)
5. Remove all accel-dependent guards in calibration function

**Do NOT start the algorithm work until you have real PPI data from the band and have validated signal quality at 6 BPM resonance breathing.**

---

## First Thing to Do When Band Arrives

Before writing any algorithm code:

1. Pair the band with iPhone/Mac via Polar Flow or Polar Sensor Logger app
2. Sit quietly, breathe at 6 breaths/min (5s in, 5s out) for 10 minutes
3. Export the raw RR/PPI data
4. Look at it — specifically:
   - Is the RSA oscillation at 0.1 Hz clearly visible in the periodogram?
   - What is the jitter level (beat-to-beat noise floor)?
   - Does the 6 BPM signal survive autocorrelation at r ≥ 0.3?
5. Only after seeing clean data should you start the algorithm work

This 2-hour data validation step will save weeks of building on wrong assumptions.

---

## Product Vision: Nervous System Fitness

**Product thesis:** ZenFlow trains your nervous system the way a coach trains an athlete — with a structured program, real metrics, and proof that it's working.

**Target user:** Not a meditator. Someone chronically stressed who:
- Has tried Calm/Headspace and quit
- Would respond to empirical proof of improvement
- Motivated by progress, not by practice
- Wants to feel less reactive, handle pressure better, sleep well

**Core reframe:** Not "meditation app." Not "HRV tracker." **Nervous system fitness.**
- Non-woo, appeals to rational/skeptical people
- Has a clear improvement arc (fitness improves with training)
- Maps directly to what we're measuring

---

## The Measurement → Practice → Proof Loop

```
MEASURE (baseline) → UNDERSTAND → PRACTICE → PROVE → ADVANCE → repeat
```

The cycle never ends. Users don't "complete" — they level up.

---

## Baseline Measurement (7-day onboarding)

7 days, not 1. HRV has natural daily variance — need the distribution.

### Physiological (passive, from band)
| Signal | What it reveals | How |
|---|---|---|
| Resting RMSSD | Baseline ANS health | 5-min morning read |
| Stress arc | How stress accumulates through day | Continuous background wear |
| Recovery speed | How fast you return to baseline after stress | Automated from HRV trend |
| Perfusion Index | Sympathetic activation intensity | PPG AC/DC ratio |
| Coherence floor | Natural sync% without guidance | First unguided session |
| Sleep HRV | Overnight recovery quality | Passive wear |

### Subjective (3 questions, every 3 days — not daily, fatigue kills compliance)
1. **Reactivity:** "In the last 3 days, how easily did small things irritate or derail you?" (1–5)
2. **Focus:** "How easy was it to concentrate when you needed to?" (1–5)
3. **Recovery:** "After something stressful, how quickly did you feel okay again?" (1–5)

Maps to physiology: reactivity → sympathetic dominance, focus → prefrontal-vagal coupling, recovery → arc duration.

### Output of baseline (what the app tells the user on day 7)
> "Your nervous system runs at 62/100 on average. Your worst times are Tuesday–Wednesday afternoons. You recover slowly from stress (avg 2.1 hours). Your coherence floor without training is 23%."

This paragraph is the hook. Nobody has told a user something this specific about their biology before.

---

## The 3 Master Metrics (User-Facing)

| Metric | What it measures | User name |
|---|---|---|
| Daily RMSSD vs personal baseline | Overall ANS health today | **Resilience** (0–100) |
| Recovery arc duration | How fast you bounce back | **Recovery Speed** |
| Coherence depth + duration | Training quality | **Session Score** |

**Resilience** is the master number. Everything feeds it. Its trajectory over 8 weeks is the empirical proof.

---

## Training Program — 4 Levels

### Level 1: Signal (Weeks 1–2)
- **Goal:** Learn to follow the signal. Don't try to improve yet.
- Session: 5 minutes, full voice + ring guidance
- Metric: Coherence floor rising (start ~20–30%, target 60%)
- Unlock: 60% sync for 3 consecutive sessions
- Design note: 60% is achievable once calibration works → dopamine hit, sets tone that this is doable

### Level 2: Depth (Weeks 3–5)
- **Goal:** Push sync% higher and hold it longer
- Session: 7 minutes, ring only (no voice except nudges)
- New mechanic: **Depth zones**

```
Zone 1:  20–40%  → Settling     (distinct colour + sound)
Zone 2:  40–60%  → Engaged
Zone 3:  60–80%  → Coherent
Zone 4:  80–100% → Flow         (reaching this first time = a moment)
```

- Metric: Time in Zone 3+ per session
- Unlock: 4 consecutive minutes in Zone 3 across 3 sessions

### Level 3: Resilience (Weeks 6–8) — the innovation
- **Goal:** Train when it's hard, not when you're calm
- Mechanic: **Hardmode sessions** — scheduled when background HRV detects a low-resilience window
- App says: "Your nervous system is under load. Training here builds real resilience."
- Borrowed from stress inoculation training (military performance psychology)
- Sessions shorter (5 min) but count more toward Resilience score
- **This is what no competitor does — sessions timed to physiology, not calendar**
- Metric: Resilience delta after hard-day sessions
- Unlock: Complete 5 hardmode sessions

### Level 4+: Maintenance & Mastery (Ongoing)
- 5 min sessions, 4x per week
- Full baseline re-run every 30 days
- Compare to day 1 → this is the product's emotional peak moment

---

## Report Card Design (Simple — One Screen)

```
┌─────────────────────────────────────┐
│  YOUR NERVOUS SYSTEM · WEEK 4       │
├─────────────────────────────────────┤
│  RESILIENCE         71  ↑ +12       │
│  [████████░░]  vs week 1: 59        │
│                                     │
│  RECOVERY SPEED    1.2h  ↓ -1.1h   │
│  [███████░░░]  vs week 1: 2.3h      │
│                                     │
│  TRAINING QUALITY   8/10            │
│  [████████░░]  4 sessions this week │
├─────────────────────────────────────┤
│  WHAT THIS MEANS                    │
│  "You're recovering from stress     │
│   twice as fast as when you started.│
│   Your body is learning."           │
├─────────────────────────────────────┤
│  THIS WEEK'S FOCUS                  │
│  Hold Zone 3 for 5 min · 3 sessions │
│  [Start today's session]            │
└─────────────────────────────────────┘
```

No charts with axes. No data tables. No HRV jargon. One sentence in plain English. One thing to do next.

---

## Nudge System (Biologically Timed — Not Calendar-Based)

- **Morning read:** 5-min baseline after waking. "Your resilience today is 58 — slightly lower than average. Session scheduled for 7pm."
- **Ultradian window:** Mid-day HRV trough detected → "Natural recovery window now — 7 minutes available."
- **Evening prompt:** Contextual on stress debt accumulated.
- **Pre-performance protocol:** 10 min before high-stakes moment → 5-min session → "Your nervous system is ready."

---

## Additional Feature Directions (Future)

1. **Stress Fingerprint** — 30-day heat map: day-of-week × time-of-day × resilience level. Unique to each user. "Schedule hard things in your green zones."

2. **Event Tagging** — One-tap: meeting, argument, exercise, coffee, alcohol, bad sleep. Correlate with HRV outcomes automatically over weeks.

3. **SpO2 Trend** — 3-channel PPG enables in-session oxygen saturation trend. Shows optimisation during coherence breathing. Viscerally compelling.

4. **Subjective × Objective Correlation** — Map 3-day check-in scores against HRV trend. By week 6: "You rated stress handling 4/10 three weeks ago. Last week: 7/10. Your RMSSD agrees — up 31%."

5. **Pre-Performance Protocol** — Acute use case. Different from chronic training but same hardware + session engine.

6. **Restlessness Score** — Gyro + arm ACC micro-movements before a session. High restlessness → suggest 60s body scan before breathing begins.

---

## Tech Stack (Expected — mirrors ZenFlow_project)

- **Backend:** Python FastAPI (bridge.py) — to be rebuilt for Verity
- **Frontend:** React + TypeScript (zenflow-ui)
- **Hardware bridge:** Swift (Polar BLE SDK) — stream PPI + PPG raw instead of ACC
- **Communication:** WebSocket (same as H10 project)

The UI layer can be largely copied from ZenFlow_project. The algorithm layer (bridge.py calibration function, confidence scoring) needs a ground-up rewrite for the no-accel signal architecture.

---

## Key Design Principles

1. **Data without meaning = abandonment.** Every number must have a plain-English sentence explaining what it means.
2. **The system tells you what to do today.** Remove decision fatigue.
3. **Progressive overload.** Borrow from strength training, not from meditation apps.
4. **Feel it before the data proves it.** Week 1–2 is the danger zone — HRV takes 3–4 weeks to measurably shift. Bridge this with subjective check-ins that show correlation by week 6.
5. **Sessions timed to physiology, not calendar.** This is the core differentiator.

---

## What to Do When This Workspace Opens Next

1. Band arrived? → Run the 10-minute data validation session (see "First Thing to Do" above)
2. Check PPI jitter and RSA peak quality at 6 BPM
3. If signal is clean: start Swift bridge for PPI streaming
4. If signal is marginal: research PAV as alternative breath signal before committing
5. Only after validated signal: begin bridge.py calibration rewrite for no-accel mode

---

*This context file is the source of truth for all product and technical decisions made before development began. Update it as decisions evolve.*
