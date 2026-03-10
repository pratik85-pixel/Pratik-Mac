# ZenFlow Verity — UI & Experience Design

**Created:** 5 March 2026  
**Status:** Design phase — pre-development

---

## Design Principles

1. **One screen, one idea.** Never more than one primary action per screen.
2. **No jargon in the UI.** Scientific terms live in tooltips only — never in the main copy. (See Language Guide below.)
3. **Optimistic always.** Every insight is framed as an opportunity, never a warning. Not "you're stressed" — "your body is ready for a reset."
4. **Instant gratification.** First meaningful insight within 24 hours. First archetype within 48 hours. No 7-day waits.
5. **The system decides.** Remove every decision from the user. They confirm, not choose.
6. **Progress is visible.** The journey map is always accessible — users can see where they are, where they've been, and what's ahead.
7. **Feel it first, prove it later.** Week 1 is about noticing sensations. Week 4–6 is where the data validates what they already feel.

---

## Language Guide — Plain English Always

The UI never uses these words directly. They live only in "Learn more" tooltips for curious users.

| ❌ Never say | ✅ Say instead |
|---|---|
| HRV / RMSSD | Body rhythm, nervous system score |
| Coherence | In sync, heart-breath sync, your body is in flow |
| Sympathetic dominance | Your body is on high alert |
| Parasympathetic | Your body is in rest mode |
| Vagal tone | Your calm system |
| RSA oscillation | Your heart and breath moving together |
| Stress marker elevated | Your body is carrying some load right now |
| Low resilience | Your body needs a reset |
| RMSSD delta | Your body shifted after the session |
| Zone 3 coherence | Deep sync |
| Lomb-Scargle | (never shown) |

**Tone always:** warm, specific, slightly personal — like a knowledgeable friend, not a clinician.

---

## The Language of Progress — Optimistic Framing

| ❌ Scary / clinical | ✅ Optimistic / actionable |
|---|---|
| "You are under stress" | "Your body is carrying some load — a reset would help right now" |
| "Your HRV is low" | "Your body rhythm is quieter than usual today — totally normal, let's work with it" |
| "Stress accumulated since Tuesday" | "Your body has been working hard since Tuesday — it's ready to unwind" |
| "Recovery arc: 2.4 hours" | "After tough moments, your body takes about 2–3 hours to feel itself again" |
| "Sympathetic dominance detected" | "Your system is in go-mode right now" |
| "Poor sleep quality" | "Your body didn't fully recharge last night — here's how to make today easier" |
| "Archetype: The Wire" | "You're a high-performer who hasn't learned to switch off yet — we can fix that" |

---

## Act 1: Onboarding — First Open (One Time)

Think iPhone first-time setup. One question per screen. Progress dots at top. Clean, white, no clutter.

```
Screen 1 — Welcome
┌─────────────────────────────────┐
│  ● ○ ○ ○ ○ ○                    │
│                                 │
│                                 │
│  Welcome to ZenFlow.            │
│                                 │
│  Your body is smarter           │
│  than you think.                │
│  We're going to prove it.       │
│                                 │
│                                 │
│       [ Let's go  →  ]          │
│                                 │
└─────────────────────────────────┘

Screen 2 — What brings you here?
┌─────────────────────────────────┐
│  ● ● ○ ○ ○ ○                    │
│                                 │
│  What's the main thing          │
│  you want to change?            │
│                                 │
│  ○  I can't switch off          │
│                                 │
│  ○  I'm always tired            │
│                                 │
│  ○  I snap at small things      │
│                                 │
│  ○  I can't focus               │
│                                 │
│  ○  I sleep badly               │
│                                 │
└─────────────────────────────────┘

Screen 3 — A typical day
┌─────────────────────────────────┐
│  ● ● ● ○ ○ ○                    │
│                                 │
│  What does your day             │
│  usually look like?             │
│                                 │
│  ○  High-pressure work,         │
│     back-to-back                │
│                                 │
│  ○  Active and on my feet       │
│                                 │
│  ○  Mostly desk-based           │
│                                 │
│  ○  Variable — no two days      │
│     are the same                │
│                                 │
└─────────────────────────────────┘

Screen 4 — Movement you enjoy
┌─────────────────────────────────┐
│  ● ● ● ● ○ ○ ○ ○                │
│                                 │
│  What movement do you           │
│  actually enjoy?                │
│  (pick all that apply)          │
│                                 │
│  ☐  Running / jogging           │
│  ☐  Cycling                     │
│  ☐  Gym / strength training     │
│  ☐  Swimming                    │
│  ☐  Hiking / long walks         │
│  ☐  Yoga / pilates              │
│  ☐  Team sports                 │
│  ☐  Nothing yet — want to start │
│                                 │
│  (We'll suggest these on        │
│  your best body days)           │
│                                 │
└─────────────────────────────────┘

Screen 5 — Things that affect your body
┌─────────────────────────────────┐
│  ● ● ● ● ● ○ ○ ○                │
│                                 │
│  A few things quietly           │
│  affect how your body           │
│  recovers. No judgment —        │
│  just helps us coach you        │
│  more accurately.               │
│                                 │
│  Alcohol:                       │
│  ○  Rarely / never              │
│  ○  Socially (few times/week)   │
│  ○  Most evenings               │
│                                 │
│  Caffeine:                      │
│  ○  1–2 cups, morning only      │
│  ○  Several cups, all day       │
│  ○  Sensitive to it             │
│                                 │
│  Sleep schedule:                │
│  ○  Fairly consistent           │
│  ○  Varies a lot                │
│                                 │
└─────────────────────────────────┘

Screen 6 — How you decompress
┌─────────────────────────────────┐
│  ● ● ● ● ● ● ○ ○                │
│                                 │
│  When you need to unwind,       │
│  what do you actually do?       │
│  (pick all that apply)          │
│                                 │
│  ☐  Exercise or sport           │
│  ☐  Reading                     │
│  ☐  Time in nature              │
│  ☐  Music                       │
│  ☐  TV / streaming              │
│  ☐  Socialising                 │
│  ☐  I just push through         │
│                                 │
│  (We'll suggest these on        │
│  your low-energy days)          │
│                                 │
└─────────────────────────────────┘

Screen 7 — The honest one
┌─────────────────────────────────┐
│  ● ● ● ● ● ● ● ○                │
│                                 │
│  One honest thing.              │
│                                 │
│  This app measures your         │
│  body — not just your habits.   │
│                                 │
│  It will notice things          │
│  about you before you do.       │
│                                 │
│  That's what makes it work.     │
│                                 │
│       [ I'm ready  →  ]         │
│                                 │
└─────────────────────────────────┘

Screen 8 — Connect band
┌─────────────────────────────────┐
│  ● ● ● ● ● ● ● ●                │
│                                 │
│  Now let's connect              │
│  your band.                     │
│                                 │
│       [  Polar logo  ]          │
│                                 │
│  Hold your Verity Sense         │
│  close to your phone...         │
│                                 │
│   ◉  Searching...               │
│                                 │
│   ✓  Verity Sense found         │
│                                 │
│       [ Connect  →  ]           │
│                                 │
└─────────────────────────────────┘
```

**Why these habit screens matter:**
- Movement preferences → coach prescribes activities the user already enjoys, never alien ones
- Alcohol / caffeine / sleep schedule → coach calibrates recovery expectations and times nudges correctly
- Decompress style → coach references their actual preferences (*"Your body is ready for that hike you enjoy"*)
- "I just push through" → flags Suppressor tendency, adjusts first archetype hypothesis accordingly

**What is NOT asked:**
- Diet or nutrition (too complex, changes coaching liability)
- Medical history (not a clinical product)
- Weight or fitness level (irrelevant — the band measures what matters)

---

## Act 2: First Reading — Instant Gratification (0–2 hours)

No 7-day wait. Within the first 2 hours of wearing the band, the user gets their first real insight. The system builds the full picture over 48 hours in the background — but the user never stares at a loading screen.

### Immediate (first 15 minutes)
The band connects and the app shows a live "getting to know you" screen with one real-time number already visible.

```
┌─────────────────────────────────┐
│                                 │
│  ZenFlow is reading             │
│  your body now.                 │
│                                 │
│  ┌───────────────────────┐      │
│  │  📡 Band connected    │      │
│  │  Reading live...      │      │
│  └───────────────────────┘      │
│                                 │
│  Right now:                     │
│                                 │
│  Your heart is beating          │
│  at  62 bpm                     │
│  (resting)                      │
│                                 │
│  Already learning               │
│  something about you.           │
│                                 │
│  Wear the band as much as       │
│  you can — including sleep.     │
│  Your first full picture        │
│  arrives in ~24 hours.          │
│                                 │
└─────────────────────────────────┘
```

### Hour 2 — First Micro-Insight Push Notification
> "ZenFlow noticed something. Your body had a stress response at 2:14pm — right before it settled. That's already useful data."

### Hour 6 — First Snapshot Available
```
┌─────────────────────────────────┐
│  Early snapshot ready           │
├─────────────────────────────────┤
│                                 │
│  Your body rhythm today:        │
│                                 │
│       68 / 100                  │
│   ███████░░░                    │
│   Good starting point           │
│                                 │
│  "Your body is in decent        │
│  shape. There's clear room      │
│  to strengthen your calm        │
│  system — and we know how."     │
│                                 │
│  Building your full picture...  │
│  ████████░░  ~18 hrs remaining  │
│                                 │
│  [ See what we know so far ]    │
│                                 │
└─────────────────────────────────┘
```

### What Builds Over 48 Hours (Invisible to User)

The model builds incrementally. What's shown vs. what requires more data:

| Data needed | Available at | Shown to user |
|---|---|---|
| Resting heart rate | 30 min | Hour 1 |
| Basic body rhythm score | 2–3 hours | Hour 6 |
| Daytime stress pattern | 8–12 hours | Day 1 evening |
| Sleep quality | After first night's wear | Day 2 morning |
| Recovery arc | After first stress + settle event | Day 1 or 2 |
| Full archetype | 24–48 hours | Day 2 |
| Exercise readiness | After sleep data | Day 2 |

**Design rule:** Show whatever is ready. Mark what's still building. Never show a blank screen. The picture fills in like a Polaroid — not all at once, which creates anticipation rather than frustration.

---

## Act 3: The Reveal — 24–48 Hours In

### Screen 1 — The Opening
```
┌─────────────────────────────────┐
│                                 │
│  We've spent 48 hours with      │
│  your nervous system.           │
│                                 │
│  We found some things           │
│  worth knowing.                 │
│                                 │
│                                 │
│      [ Show me  →  ]            │
│                                 │
└─────────────────────────────────┘
```

### Screens 2–4 — The Three Pillars (one swipe each)
```
Swipe 1 — Energy                   Swipe 2 — Recovery
┌─────────────────────┐            ┌─────────────────────┐
│  YOUR ENERGY        │            │  BOUNCE-BACK         │
│  SYSTEM             │            │  SPEED               │
│                     │            │                      │
│    68 / 100         │            │    ~2.4 hours        │
│  ███████░░░         │            │                      │
│                     │            │  After a tough       │
│  "Your calm system  │            │  moment, your body   │
│  is working but     │            │  takes about 2–3hrs  │
│  not yet at full    │            │  to feel itself      │
│  strength. Think of │            │  again.              │
│  it like a muscle   │            │                      │
│  that hasn't been   │            │  "Most people your   │
│  trained yet."      │            │  age bounce back     │
│                     │            │  in about an hour.   │
│                     │            │  This is very        │
│  ● ○ ○              │            │  trainable."         │
│                     │            │                      │
│  ┌───────────────┐  │            │  ○ ● ○               │
│  │ ℹ The science │  │            └─────────────────────┘
│  └───────────────┘  │
└─────────────────────┘

Swipe 3 — Sleep
┌─────────────────────┐
│  SLEEP & RESTORE    │
│                     │
│    Moderate         │
│  ██████░░░░         │
│                     │
│  "You're sleeping   │
│  long enough, but   │
│  your body's deep   │
│  restore phase is   │
│  being cut short    │
│  most nights."      │
│                     │
│  "The good news:    │
│  this responds      │
│  quickly to         │
│  training."         │
│                     │
│  ○ ○ ●              │
└─────────────────────┘
```

**Note on the "ℹ The science" button:** tapping this reveals a clean tooltip with the actual term — "This score is based on Heart Rate Variability (HRV), a measure used in clinical research to assess autonomic nervous system health." Satisfies the skeptic without cluttering the main screen.

### Screen 5 — The Archetype
```
┌─────────────────────────────────┐
│                                 │
│  Based on how your body         │
│  actually behaved these         │
│  past 48 hours...               │
│                                 │
│  ┌─────────────────────────┐    │
│  │                         │    │
│  │  ⚡  THE WIRE            │    │
│  │                         │    │
│  │  You're built for        │    │
│  │  performance. Your body  │    │
│  │  goes hard — it just     │    │
│  │  hasn't learned to       │    │
│  │  properly switch off.    │    │
│  │                         │    │
│  └─────────────────────────┘    │
│                                 │
│  + Slow Burner tendencies       │
│  Stress builds quietly through  │
│  your week and peaks Thursday.  │
│  You likely feel it on Friday.  │
│                                 │
│  [ Yes, that's me  →  ]         │
│  [ Not quite right     ]        │
│                                 │
└─────────────────────────────────┘
```

### Screen 6 — The Promise (Optimistic, Specific)
```
┌─────────────────────────────────┐
│                                 │
│  Here's what 8 weeks of         │
│  ZenFlow does for a Wire.       │
│                                 │
│  ENERGY SYSTEM    68 → 81       │
│  ████████░░  ░░░░░░████         │
│                                 │
│  BOUNCE-BACK     2.4h → 1.0h    │
│  ████████░░  ░░░░░░████         │
│                                 │
│  SLEEP QUALITY    62 → 76       │
│  ████████░░  ░░░░░░████         │
│                                 │
│  These aren't promises.         │
│  They're averages from real     │
│  people who started like you.   │
│                                 │
│  Your program starts            │
│  tomorrow.                      │
│                                 │
│       [ I'm in  →  ]            │
│                                 │
└─────────────────────────────────┘
```

---

## Act 4: The Daily Experience

### Home Screen — Every Day (Updated 9 March 2026)

The home screen shows three numbers and one sentence. Nothing else above the fold. This is the user's daily relationship with their body.

```
┌─────────────────────────────────┐
│  Good morning, Pratik.   07:34  │
├─────────────────────────────────┤
│                                 │
│  YESTERDAY                      │
│                                 │
│  ┌─────────┐ ┌─────────┐        │
│  │ STRESS  │ │RECOVERY │        │
│  │   72    │ │   85    │        │
│  │ [██████]│ │ [██████]│        │
│  │peaked 3p│ │sleep did│        │
│  │         │ │the work │        │
│  └─────────┘ └─────────┘        │
│                                 │
│           TODAY                 │
│    ┌─────────────────┐          │
│    │   READINESS     │          │
│    │       71        │          │
│    │  [███████░░░]   │          │
│    │   strong start  │          │
│    └─────────────────┘          │
│                                 │
│  "You absorbed a hard day       │
│   and came back close to        │
│   full. You're ready."          │
│                                 │
├─────────────────────────────────┤
│  TODAY'S SESSION                │
│  ◉  Breathing · Best at 7pm    │
│  [ Start now ]                  │
└─────────────────────────────────┘
```

**How the three numbers read:**
- **Stress (yesterday):** How much ANS stress accumulated from wake to sleep. 72 = used 72% of your personal stress capacity.
- **Recovery (yesterday):** How much recovery credit your body deposited from yesterday's morning read to this morning's. 85 = strong recovery, sleep did the work.
- **Readiness (today):** Net position, calibrated by this morning's physiological read. 71 = (85 − 72 = +13 net) × morning read calibration.

Tapping any number goes to its detail screen.

---

### Stress Detail Screen

Accessed by tapping the STRESS number.

```
┌─────────────────────────────────┐
│  ←  YESTERDAY'S STRESS     72   │
├─────────────────────────────────┤
│                                 │
│  YOUR NS LOAD THROUGH THE DAY   │
│                                 │
│  %  above ─ ─ ─ ─ ─ ─ ─ ─ ─    │
│  avg│                  ╭──╮     │
│     │         ╭──╮    ╭╯  ╰─╮  │
│  ───┼─────────╯  ╰────╯     ╰  │
│     │  ╭──╮                    │
│     │╮╭╯  ╰────────────────    │
│  blw│╰╯                        │
│  avg└──────────────────────     │
│    7a  10   1p   4    7    10p  │
│                                 │
│  ────── WHAT USED YOUR ENERGY ──│
│                                 │
│  ┌──────────────────────────┐   │
│  │ 🏃 Morning run   10:15a  │   │
│  │      ████████░░  31%     │   │
│  │      Physical load       │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ 💼 Work stress   2:30p   │   │
│  │      ██████░░░░  22%     │   │
│  │      Work / calls        │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ ❓ 6:00pm – 6:45pm       │   │
│  │      ████░░░░░░  14%     │   │
│  │      Untagged  [ Tag? ]  │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ ··· smaller events   5%  │   │
│  └──────────────────────────┘   │
│                                 │
│  Remaining 28% = background     │
│  activity (below threshold)     │
│                                 │
└─────────────────────────────────┘
```

**Design rules:**
- Waveform: RMSSD normalized to personal average (1.0 = your average). Shaded fill below the line = stress debt area. Each labelled event is a coloured band on the waveform.
- Itemized rows sorted by contribution (largest first).
- Each row shows: icon, time, contribution bar, % of day total, tag label.
- Untagged rows show "Untagged — Tag?" in a subtle accent colour. Tapping opens the Tag Sheet.
- "Smaller events" row collapses events below 5% contribution to reduce clutter.
- No jargon — "energy" not "RMSSD", "your baseline" not "personal morning average".

---

### Recovery Detail Screen

Accessed by tapping the RECOVERY number.

```
┌─────────────────────────────────┐
│  ←  YESTERDAY'S RECOVERY   85   │
├─────────────────────────────────┤
│                                 │
│  HOW YOUR BODY RECHARGED        │
│                                 │
│  %   above ─ ─ ─ ─ ─ ─ ─ ─     │
│  avg │╭──────────────────────╮  │
│      ││  (green fill = credit)│  │
│  ────┼┼─────────────────────  │  │
│      ╰╯                         │
│      └─────────────────────     │
│    7a  10   1p   4    7   10p   │
│                                 │
│  ──── WHERE YOUR RECOVERY CAME ─│
│                                 │
│  ┌──────────────────────────┐   │
│  │ 🌙 Sleep         11pm–7am│   │
│  │      █████████░  52%     │   │
│  │      Deep restore        │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ ◉  ZenFlow session  7pm  │   │
│  │      ██████░░░░  24%     │   │
│  │      Breathing · 5min    │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ 🌿 Recovery window  5pm  │   │
│  │      ████░░░░░░  16%     │   │
│  │      What were you doing?│   │
│  │      [ Tag? ]            │   │
│  └──────────────────────────┘   │
│                                 │
│  Remaining 8% = small natural   │
│  recovery moments through day   │
│                                 │
└─────────────────────────────────┘
```

**Design rules:**
- Same waveform style but above-line area filled green (recovery credit).
- Sleep contribution always shown first — it's the dominant mechanism and users should know this.
- ZenFlow sessions auto-tagged, shown with session icon.
- Untagged recovery windows shown with gentle "What were you doing?" prompt (not "Tag?") — warmer framing because recovery is good news.

---

### Readiness Overlay Screen

Accessed by tapping the READINESS number.

```
┌─────────────────────────────────┐
│  ←  TODAY'S READINESS      71   │
├─────────────────────────────────┤
│                                 │
│  YOUR BODY YESTERDAY            │
│                                 │
│  %   above ─ ─ ─ ─ ─ ─ ─ ─     │
│  avg │           ╭──────────╮   │
│      │  ╭──╮    ╭╯  (green) ╰─  │
│  ────┼─╮╯  ╰────╯              │
│      │╭╯ (red fill)            │
│      ╰╯                        │
│      └─────────────────────    │
│    7a  10   1p   4    7   10p  │
│                                 │
│    ▓▓ Recovery credit (green)   │
│    ░░ Stress debt (red)         │
│                                 │
│  ─────────────────────────────  │
│  YESTERDAY                      │
│  Stress   ██████████░  72       │
│  Recovery █████████░░  85       │
│  Net      +13  ✓ Positive       │
│                                 │
│  THIS MORNING                   │
│  Body check-in at 7:14am        │
│  "Body confirmed: stronger      │
│  than the math suggested"       │
│  Readiness →  71                │
│                                 │
│  "Your recovery outpaced your   │
│  stress. Sleep did the work.    │
│  You're starting strong."       │
│                                 │
└─────────────────────────────────┘
```

**Design rules:**
- Both waveforms overlaid — red fill below baseline, green fill above.
- Net position shown as a simple +/− number with a plain label ("Positive" / "In deficit").
- Morning read shown as the calibration event: a vertical marker at morning read time with the final readiness number.
- The sentence explains what the number actually means in plain English.

---

### Tag Sheet (Bottom Sheet — Triggered by "Tag?" Tap)

Appears from the bottom. Maximum 4 options + Skip. Closes in under 5 seconds.

```
┌─────────────────────────────────┐
│        [drag handle]            │
│                                 │
│  What was happening             │
│  around 6:00pm?                 │
│                                 │
│  ┌─────────┐  ┌─────────┐       │
│  │ 🏃      │  │ 💼      │       │
│  │ Workout │  │  Work   │       │
│  └─────────┘  └─────────┘       │
│  ┌─────────┐  ┌─────────┐       │
│  │ 💬      │  │ 🌿      │       │
│  │ Social/ │  │ Walk /  │       │
│  │argument │  │ nature  │       │
│  └─────────┘  └─────────┘       │
│                                 │
│       [ Skip for now ]          │
│                                 │
└─────────────────────────────────┘
```

**Design rules:**
- Context-adaptive: the 4 options shown are tailored to whether it's a stress or recovery window.
  - Stress window options: Workout, Work/calls, Argument / difficult, Other physical
  - Recovery window options: Walk / nature, Reading / music, Social / family, ZenFlow session
- "Skip for now" is always available, never penalised in UI — the window still contributes to the score.
- No text input on the tag sheet — tapping one option confirms and closes instantly.

---

### Nudge Design — Spike-Triggered, Post-Event

Nudges appear as notifications. Maximum 3 per day. Always post-event (sent after the stress window closes, not during).

```
Notification (lock screen / banner):
┌──────────────────────────────┐
│  ZenFlow                     │
│                              │
│  Active period around 3:15pm │
│  — workout or something      │
│  else?                       │
│                              │
│  [ Tag it ]   [ Skip ]       │
└──────────────────────────────┘
```

Tapping "Tag it" opens directly to the Tag Sheet for that event. Tapping "Skip" dismisses — the event remains untagged.

**Significant spike rule:** If a single stress event contributed > 25% of daily capacity, one nudge fires even if the 3-nudge cap was reached. This is the only override. It fires the same way — post-event, never during.

**Tone of nudge copy:**
- Never alarming: not "High stress detected" — "Active period around 3:15pm"
- Never pressuring: "— workout or something else?" not "Please tag this event"
- Recovery nudge (softer): "Your body settled around 5:30pm — what helped?"

---

### Calibrating State (Days 1–3) — What the User Sees

```
HOME SCREEN — Day 1 evening
┌─────────────────────────────────┐
│  Welcome, Pratik.        19:42  │
├─────────────────────────────────┤
│  ZenFlow is learning your body. │
│                                 │
│  First readings available       │
│  in ~12 hours.                  │
│                                 │
│  LIVE NOW                       │
│  ┌────────────────────────┐     │
│  │  Heart rate:  64 bpm   │     │
│  │  Rhythm: settling ░░░░ │     │
│  └────────────────────────┘     │
│                                 │
│  Keep the band on today.        │
│  Especially tonight.            │
│  Sleep data is the biggest      │
│  unlock.                        │
└─────────────────────────────────┘
```

```
HOME SCREEN — Day 2 (provisional scores)
┌─────────────────────────────────┐
│  Good morning, Pratik.   07:22  │
├─────────────────────────────────┤
│  YESTERDAY  (early estimate ·)  │
│                                 │
│  ┌─────────┐ ┌─────────┐        │
│  │ STRESS  │ │RECOVERY │        │
│  │ ~61 est │ │ ~74 est │        │
│  │ [█████░]│ │ [██████]│        │
│  └─────────┘ └─────────┘        │
│                                 │
│  READINESS ~59 est              │
│  [██████░░░]                    │
│                                 │
│  Getting more accurate as       │
│  your baseline builds.          │
│  Ready in ~2 more days.         │
└─────────────────────────────────┘
```

---

### History View — Multi-Day Summary

Accessed from the Home screen via "History" or calendar icon.

```
┌─────────────────────────────────┐
│  ←  MY HISTORY                  │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─    │
│  Mon  Tue  Wed  Thu  Fri  Sat   │
│   72   58   81   69   44   ──   │
│  (stress scores shown as bars)  │
│                                 │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─    │
│  ▼ THURSDAY                     │
│  Stress 69  Recovery 71         │
│  Readiness that morning: 62     │
│                                 │
│  Biggest stress: Work (2pm)     │
│  Biggest recovery: Sleep        │
│                                 │
│  [ See full day ]               │
└─────────────────────────────────┘
```

---

### Training Day Types — Physical Exercise Cards

The daily plan includes one physical card. Framing is always capacity-based, never punitive.

```
GREEN DAY — Full capacity (Readiness ≥ 70)
┌─────────────────────────────────┐
│  💪  MOVEMENT TODAY             │
│                                 │
│  Your body is strong today.     │
│                                 │
│  ✓  Cardio (20–30 min)         │
│     Running, cycling, swimming  │
│     — whatever you enjoy        │
│                                 │
│  or                             │
│                                 │
│  ✓  Strength training           │
│     Keep it to 30 min max.      │
│     Quality over volume.        │
│                                 │
│  "Exercise today will make      │
│  tomorrow's body rhythm         │
│  even stronger."                │
└─────────────────────────────────┘

YELLOW DAY — Working with load (Readiness 45–69)
┌─────────────────────────────────┐
│  🚶  MOVEMENT TODAY             │
│                                 │
│  Your body is carrying some     │
│  load today.                    │
│                                 │
│  ✓  Light movement only         │
│     20-min walk                 │
│     Gentle stretching / yoga    │
│                                 │
│  ✗  Skip intense exercise       │
│     A hard session today would  │
│     work against you, not for   │
│     you. Save it for tomorrow.  │
│                                 │
│  "Movement is still medicine    │
│  today — just the gentle kind." │
└─────────────────────────────────┘

RED DAY — Recovery day (Readiness < 45)
┌─────────────────────────────────┐
│  🛁  REST TODAY                 │
│                                 │
│  Your body is asking for        │
│  a real break.                  │
│                                 │
│  ✓  Gentle walk if you feel     │
│     like it — nothing more      │
│                                 │
│  ✓  Your breathing session      │
│     is still on — it's 5 mins   │
│     and will speed up your      │
│     recovery                    │
│                                 │
│  "Rest is not wasted time.      │
│  This is when your body         │
│  actually gets stronger."       │
└─────────────────────────────────┘
```

---

### The Live Session Screen
```
┌─────────────────────────────────┐
│  ←  Session          Day 4 · L1 │
├─────────────────────────────────┤
│                                 │
│        ╔═══════════╗            │
│      ╔═╝           ╚═╗          │
│     ╔╝  BREATHE IN   ╚╗        │
│     ║                 ║         │
│     ║   ● ● ●   IN    ║  FLOW  │
│     ║   SYNC          ║  ████░ │
│     ║   71%           ║  ZONE 3│
│     ╚╗               ╔╝         │
│      ╚═╗           ╔═╝          │
│        ╚═══════════╝            │
│                                 │
│         3:24 remaining          │
│                                 │
│  ─────────────────────────────  │
│  Your sync this session:        │
│  ░░░░░█████░░███████░░  71%avg  │
│         SETTLING  IN SYNC FLOW  │
│                                 │
└─────────────────────────────────┘
```

**Language on the ring:**
- Zone 1 → "Settling" (warm grey)
- Zone 2 → "Finding it" (soft blue)
- Zone 3 → "In Sync" (calm green)
- Zone 4 → "Flow" (deep green / gold)

No percentages on the ring itself — just the label. The number is a secondary detail below.

---

### Post-Session Screen
```
┌─────────────────────────────────┐
│                                 │
│     Session complete.           │
│                                 │
│  ┌───────────────────────┐      │
│  │   YOU WERE IN SYNC    │      │
│  │   71% of the time     │      │
│  │   ████████░░          │      │
│  │   Your best this week │      │
│  └───────────────────────┘      │
│                                 │
│  Before →  After                │
│  Body carrying load  →  Calm    │
│  "Your body visibly shifted     │
│  in 5 minutes. That's the       │
│  mechanism working."            │
│                                 │
│  ─────────────────────────────  │
│  "Three sessions ago you were   │
│  in sync 34% of the time.       │
│  Today: 71%. Keep going."       │
│                                 │
│  ─────────────────────────────  │
│  Tomorrow: Same session, 7pm    │
│                                 │
│       [ Done ]                  │
│                                 │
└─────────────────────────────────┘
```

---

## Act 5: The Journey Map — Progress Always Visible

Accessible from the home screen via a "My Journey" tab. Shows past and future in one view.

```
┌─────────────────────────────────┐
│  MY JOURNEY             Week 4  │
├─────────────────────────────────┤
│                                 │
│  STAGE 1 · SIGNAL    ✓ Done     │
│  ████████████████████           │
│  Learned to get in sync         │
│  Completed: Week 2              │
│                                 │
│  STAGE 2 · DEPTH   ← You are   │
│  ████████░░░░░░░░░░  here       │
│  Pushing sync deeper & longer   │
│  Progress: 4 of 7 sessions      │
│  Unlock: Hold deep sync         │
│           for 5 min × 3 times   │
│                                 │
│  STAGE 3 · RESILIENCE  🔒       │
│  ░░░░░░░░░░░░░░░░░░░░           │
│  Train when it's hard           │
│  Unlocks when Stage 2 done      │
│                                 │
│  STAGE 4 · MASTERY     🔒       │
│  ░░░░░░░░░░░░░░░░░░░░           │
│  Your new normal                │
│                                 │
├─────────────────────────────────┤
│  MILESTONES                     │
│  ✓ First session complete       │
│  ✓ First deep sync moment       │
│  ✓ Stage 1 completed            │
│  ◉ 5-day streak (3 to go)       │
│  ○ First Flow state             │
│  🔒 Stage 3 unlocked            │
└─────────────────────────────────┘
```

---

## Act 6: Level Unlock — The Earned Moment

Appears as the first screen on the morning after criteria are met.

```
┌─────────────────────────────────┐
│                                 │
│   Something changed last        │
│   night.                        │
│                                 │
│  ┌─────────────────────────┐    │
│  │  ★  STAGE 2 UNLOCKED    │    │
│  │     DEPTH               │    │
│  └─────────────────────────┘    │
│                                 │
│  You've been in sync above      │
│  60% for 3 sessions running.    │
│  Your calm system has learned   │
│  the signal.                    │
│                                 │
│  Now we go deeper.              │
│                                 │
│  What's new:                    │
│  • Sessions: 5 min → 7 min      │
│  • Voice guidance fades out     │
│  • Depth levels introduced      │
│  • Extended exhale unlocked     │
│                                 │
│  [ See my new plan  →  ]        │
│                                 │
└─────────────────────────────────┘
```

---

## Act 7: Progress Over Time — The Report Card

### Weekly Snapshot (Sunday)
```
┌─────────────────────────────────┐
│  YOUR WEEK 4                    │
├─────────────────────────────────┤
│                                 │
│  ENERGY SYSTEM      74  ↑ +12   │
│  ████████░░  4 weeks ago: 62    │
│                                 │
│  BOUNCE-BACK       1.2h  ↓ -1h  │
│  ███████░░░   4 weeks ago: 2.3h │
│                                 │
│  IN SYNC TIME       4/5 days    │
│  ████████░░  Sessions completed │
│                                 │
├─────────────────────────────────┤
│  "You're recovering from tough  │
│  moments twice as fast as when  │
│  you started.                   │
│  Your body is learning."        │
│                                 │
├─────────────────────────────────┤
│  THIS WEEK'S FOCUS              │
│  Hold deep sync for 5 min       │
│  across 3 sessions              │
│                                 │
│  [ Start today  →  ]            │
└─────────────────────────────────┘
```

### 30-Day Review — The Emotional Peak
```
┌─────────────────────────────────┐
│  30 DAYS IN                     │
├─────────────────────────────────┤
│                                 │
│            Day 1  →  Today      │
│                                 │
│  Energy     62       78   ↑+16  │
│  Bounce-back 2.4h   1.1h  ↑    │
│  Sleep       58       72   ↑+14 │
│  In-sync     34%     69%   ↑    │
│                                 │
├─────────────────────────────────┤
│                                 │
│  "You came in as a Wire.        │
│                                 │
│   You now switch off            │
│   twice as fast after           │
│   tough moments.                │
│                                 │
│   That's not just a score       │
│   going up. That's your         │
│   nervous system                │
│   actually changing."           │
│                                 │
├─────────────────────────────────┤
│  YOUR TYPE IS SHIFTING          │
│                                 │
│  ⚡ The Wire    ████████░░  →    │
│  ✦ Responder   ░░░████░░░       │
│                                 │
│  [ Share my progress ]          │
│  [ Begin Month 2  →  ]          │
└─────────────────────────────────┘
```

### Long-Term Progress Graph (Simple)
```
┌─────────────────────────────────┐
│  ENERGY OVER TIME               │
│                                 │
│  100 │                      ╭── │
│      │                   ╭──╯   │
│   75 │              ╭────╯      │
│      │         ╭────╯           │
│   50 │    ╭────╯                │
│      │────╯                     │
│   25 │                          │
│      └──────────────────────    │
│      Wk1  Wk2  Wk4  Wk6  Wk8   │
│                                 │
│  "Every dip is your body        │
│  absorbing training.            │
│  The trend is what matters."    │
│                                 │
│  [ Recovery Speed ]             │
│  [ Sleep Quality  ]             │
│  [ In-Sync Time   ]             │
└─────────────────────────────────┘
```

**Graph design rules:**
- No axis numbers — just the shape and direction
- Annotations on significant moments ("First Flow state here")
- Trendline always shown. Individual dips explained, not alarmed about.
- Toggle between the 3 core metrics. Nothing else.

---

## Act 8: The Daily Loop — Full Picture

```
Night (band worn during sleep)
        │  Body rhythm during sleep captured passively
        ▼
Morning app open
        │  Coach reads: last night's sleep, morning body rhythm, yesterday's session
        ▼
Home screen
        │  One coach sentence + today's 2–3 item plan + one Start button
        ▼
Mid-day (if triggered)
        │  Nudge: "Your body just hit a natural rest window — 3 minutes now pays off"
        ▼
Session window (evening, or prescribed time)
        │
        ├── User completes session → Post-session screen with before/after shift
        │
        └── User skips → Next morning: "Your body missed its reset yesterday.
                          Today's session matters a bit more because of it."
                          (Forward-looking. No guilt.)
        ▼
Check-in (every 3 days)
        │  3 questions: how reactive, how focused, how fast you recovered
        │  Feeds the gap between what you feel and what your body shows
        ▼
Every Sunday
        │  Weekly report card delivered
        ▼
Level gate met
        │  Stage unlock screen on next morning open
        ▼
Day 30
        │  Full comparison reveal — the emotional peak of the product
        ▼
Month 2 begins — updated plan, refined archetype, new targets
```

---

## Act 9: The Conversation Layer — Your Coach Talks Back

The coach isn't just a morning message. At any point, the user can speak or type to the coach and get a real, contextual response that can change today's plan.

### Where It Lives in the UI

A persistent coach icon is always visible in the bottom navigation bar. One tap opens the conversation. Available any time — morning, mid-day, after a session, before bed.

```
Home screen bottom nav:
┌─────────────────────────────────┐
│                                 │
│  [Home] [Session] [🎙 Coach]    │
│                                  [Journey]
└─────────────────────────────────┘
```

---

### Mode 1 — Morning Check-In (Coach Asks First)

Each morning, after the brief loads, the coach prompts once. User can respond or dismiss.

```
┌─────────────────────────────────┐
│  ← Coach                  07:34 │
├─────────────────────────────────┤
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "Your body recharged   │    │
│  │  well last night.       │    │
│  │  Before I show you      │    │
│  │  today's plan —         │    │
│  │  how are you actually   │    │
│  │  feeling?"              │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │  You                    │    │
│  │  "Pretty stressed.      │    │
│  │  Big presentation       │    │
│  │  this morning."         │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "Got it. I've moved    │    │
│  │  your session to        │    │
│  │  before your            │    │
│  │  presentation — not     │    │
│  │  this evening.          │    │
│  │  5 minutes will change  │    │
│  │  how you show up."      │    │
│  │                         │    │
│  │  ┌─────────────────┐   │    │
│  │  │ ⚡ Plan updated  │   │    │
│  │  │ Session: 8:45am │   │    │
│  │  └─────────────────┘   │    │
│  └─────────────────────────┘    │
│                                 │
│  ────────────────────────────── │
│  [  🎙 Hold to speak  ]         │
│  [  Type instead      ]         │
└─────────────────────────────────┘
```

**The plan-updated badge is key.** The user can see in real time that telling the coach something changed their actual day. That's what makes it feel like a real coach, not a journaling feature.

---

### Mode 2 — Reactive Check-In (User Initiates, Anytime)

User opens the coach at any point during the day and says anything. No prompts needed.

```
┌─────────────────────────────────┐
│  ← Coach                  14:23 │
├─────────────────────────────────┤
│                                 │
│  ┌─────────────────────────┐    │
│  │  You                    │    │
│  │  "I feel guilty —       │    │
│  │  I had a few drinks     │    │
│  │  last night."           │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "No guilt needed.      │    │
│  │  Your body showed it    │    │
│  │  this morning — your    │    │
│  │  rhythm was quieter     │    │
│  │  than usual. That's     │    │
│  │  just information,      │    │
│  │  not a failure.         │    │
│  │                         │    │
│  │  Tonight's session      │    │
│  │  will help clear it.    │    │
│  │  Same plan or scale     │    │
│  │  back?"                 │    │
│  └─────────────────────────┘    │
│                                 │
│  [ Keep the plan ]              │
│  [ Scale it back  ]             │
│                                 │
│  ────────────────────────────── │
│  [  🎙 Hold to speak  ]         │
└─────────────────────────────────┘
```

**Other reactive scenarios handled naturally:**

| User says | Coach responds + what changes |
|---|---|
| "I can't do a session today — packed schedule" | Reschedules to tomorrow, offers 3-min micro-reset instead |
| "I feel really stressed today" | Validates with body data, elevates session priority, tone shifts to compassion |
| "I went for a run this morning" | Logs it, checks against HRV — "Your body handled it well. Good choice." |
| "Work has been brutal for two weeks" | Surfaces the body data that confirms it, frames as chronic load, adjusts expectations |
| "I'm thinking of skipping this week" | Doesn't guilt-trip. Offers minimum effective dose. References their progress. |

---

### Mode 3 — Post-Session Debrief (Optional)

After the session score screen, the coach asks one question. User can skip or respond.

```
┌─────────────────────────────────┐
│  ← Coach             After sess │
├─────────────────────────────────┤
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "You were in sync 71%  │    │
│  │  of the time — your     │    │
│  │  best this week.        │    │
│  │                         │    │
│  │  How did that feel      │    │
│  │  compared to last       │    │
│  │  week?"                 │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │  You                    │    │
│  │  "Better. I noticed I   │    │
│  │  could settle faster    │    │
│  │  this time."            │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "That's the training   │    │
│  │  working. Settling      │    │
│  │  faster is the first    │    │
│  │  sign your nervous      │    │
│  │  system is learning.    │    │
│  │  Remember that on the   │    │
│  │  days it feels          │    │
│  │  harder."               │    │
│  └─────────────────────────┘    │
│                                 │
│       [ Done ]                  │
└─────────────────────────────────┘
```

---

### The Safety Guardrail — Non-Negotiable

If the coach detects language indicating something beyond stress and training — hopelessness, feeling worthless, harm-related language — it exits coaching mode immediately and warmly.

```
┌─────────────────────────────────┐
│  ← Coach                        │
├─────────────────────────────────┤
│                                 │
│  ┌─────────────────────────┐    │
│  │  🎙 ZenFlow Coach       │    │
│  │                         │    │
│  │  "I hear you. What       │    │
│  │  you're describing      │    │
│  │  sounds like more than  │    │
│  │  stress — and that      │    │
│  │  matters.               │    │
│  │                         │    │
│  │  ZenFlow can support    │    │
│  │  your physical          │    │
│  │  recovery, but for      │    │
│  │  what you're feeling    │    │
│  │  right now, talking to  │    │
│  │  someone directly       │    │
│  │  would help more."      │    │
│  │                         │    │
│  │  [ Find support →  ]    │    │
│  │                         │    │
│  │  "I'm still here for    │    │
│  │  your training whenever │    │
│  │  you're ready."         │    │
│  └─────────────────────────┘    │
│                                 │
└─────────────────────────────────┘
```

---

### Voice Input UX Rules

- **Hold to speak** — not always-on listening. User has full control.
- **Transcript shown** — what the app heard is always visible before it responds. User can correct.
- **Text option always present** — voice is not forced. Quiet environments, public spaces, personal preference.
- **Response always text + optional voice** — coach speaks the response if voice was used, stays silent if text was used.
- **Conversation history saved** — user can scroll back. The coach remembers. References past conversations by date.

---

## Scientific Credibility — The Balance

Users shouldn't think it's unscientific. They also shouldn't need a medical degree to use it.

### The Three-Layer Rule

**Layer 1 — What the user sees (plain English):**
> "Your body is in good sync today."

**Layer 2 — Available on tap (one sentence of science):**
> "Measured by Heart Rate Variability (HRV) — used in sports science and clinical research."

**Layer 3 — Available on deeper tap (full explanation):**
> "HRV measures the variation in time between heartbeats. Higher variation at rest indicates a healthy, adaptable nervous system. ZenFlow tracks your RMSSD (root mean square of successive differences), a clinically validated HRV metric used in cardiovascular and performance research."

The user never sees Layer 3 unless they want it. But it's always there. This is what makes it trustworthy without being intimidating.

---

## What the UI Never Does

- Shows a number without a plain-English sentence explaining it
- Uses the word "HRV", "RMSSD", "coherence", or "sympathetic" in main copy
- Shows more than one primary action on any screen
- Punishes missed sessions (always forward-looking)
- Shows a graph with axes, labels, and multiple data series
- Tells the user they are stressed, failing, or below average
- Gives the user a decision to make — the system always recommends, user confirms
- Uses always-on listening — voice is push-to-talk, user-initiated only
- Lets the conversation become a therapy or journaling feature — it always ends with a clear action
- Handles clinical distress signals — those are always handed off with warmth to professional resources
- References habit inputs judgementally — alcohol, caffeine, etc. are context, never moral scores

---

*This file captures UI and experience design decisions. Update as design evolves.*
