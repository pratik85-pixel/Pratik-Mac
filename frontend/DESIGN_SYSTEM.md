# ZenFlow UI Design System
**Single source of truth for all screens.**
Reference the component implementations in `src/ui/zenflow-ui-kit.tsx`.

---

## Core Reusable Components

These components are defined in `zenflow-ui-kit.tsx` and **must be reused**. Do not re-implement them.

| Component | Purpose |
|---|---|
| `ZenScreen` | Root screen wrapper with gradient background |
| `SurfaceCard` | Translucent glass card (primary card type) |
| `SectionCard` | Slightly more opaque card for grouped content |
| `SectionEyebrow` | Section label (uppercase, muted, spaced) |
| `ScoreRing` | SVG circular score ring (stress/recovery/readiness) |
| `ScoreTile` | Compact score display tile |
| `CoachSummary` | Coach brief card |
| `ZenPrimaryButton` | Primary CTA button |
| `InfoCard` | Informational callout card |
| `StressChartCard` | Stress waveform chart card |
| `RecoveryChartCard` | Recovery chart card |
| `RecoveryEventRow` | Single recovery event row |
| `BreakdownRow` | Label + value breakdown row |
| `MiniProgress` | Small horizontal progress bar |
| `PlanActivityCard` | Plan activity list item |
| `ChatBubble` | Coach conversation bubble |
| `HistoryDayCard` | History day summary card |
| `PlanMiniRing` | 56px mini ring for plan item progress |
| `MetricStatCard` | 2-column stat card (plan detail sheet) |
| `TrendPolyChart` | 3-line SVG trend chart (History screen) |
| `ReportCardRow` | Letter grade + progress bar row |
| `HealthLineChart` | Single-line sparkline chart |
| `HealthMetricCard` | Value + unit + status metric card |

---

## Color Palette

```
ZEN.colors.stress      = '#19B5FE'   // blue
ZEN.colors.recovery    = '#39E27D'   // green
ZEN.colors.readiness   = '#F2D14C'   // yellow
ZEN.colors.white       = '#FFFFFF'
ZEN.colors.bgTop       = '#132235'
ZEN.colors.bgMid       = '#0A111A'
ZEN.colors.bgBottom    = '#05090E'
ZEN.colors.surface     = 'rgba(255,255,255,0.03)'
ZEN.colors.surfaceSoft = 'rgba(255,255,255,0.025)'
ZEN.colors.border      = 'rgba(255,255,255,0.08)'
ZEN.colors.textNear    = 'rgba(255,255,255,0.94)'
ZEN.colors.textLabel   = 'rgba(255,255,255,0.58)'
ZEN.colors.textMuted   = 'rgba(255,255,255,0.45)'
```

Do **not** introduce new bright colors.

---

## Typography Scale

| Role | Size | Weight | Letter Spacing | Color |
|---|---|---|---|---|
| Eyebrow label | 10–11px | 400 | 0.22–0.24em uppercase | `textMuted` |
| Body | 14px | 400 | normal | `textLabel` |
| Sub-body | 12–13px | 400 | normal | `textMuted` |
| Card title | 15–16px | 500–600 | -0.02em | `textNear` |
| Screen title | 22px | 600 | -0.5 | `white` |
| Primary value | 24–40px | 600 | -0.03em | `white` |
| Hero value | 34px | 600 | -0.04em | `white` |

---

## Corner Radius Scale

| Element | Radius |
|---|---|
| Screen shell | 34px |
| Section / sheet top | 28–30px |
| Card | 20–24px |
| Button | 16–20px |
| Metric card | 18–20px |
| Row item | 14–18px |
| Pill / chip | 999 (full) |

---

## Spacing Rhythm

`4 → 8 → 12 → 16 → 20 → 24 → 28 → 32px`

Standard card padding: `14–20px`  
Section gap: `12px`  
Row gap: `10px`  
Grid gap: `10px`

---

## Background & Surfaces

- Background: dark radial gradient `bgTop → bgMid → bgBottom`
- `SurfaceCard`: `rgba(255,255,255,0.03)` fill + `rgba(255,255,255,0.08)` border
- `SectionCard`: slightly more opaque, same border
- All cards: `borderRadius 20–24px`, `borderWidth: 1`

---

## Charts

- Grid lines: `rgba(255,255,255,0.08)`, 1px, horizontal only
- Stroke width: `2.5–3px`
- Colors: stress=`#19B5FE`, recovery=`#39E27D`, readiness=`#F2D14C`
- `strokeLinecap="round"`, `strokeLinejoin="round"`
- No filled areas (lines only)
- Axes: no visible axis lines, only subtle grid

---

## Interaction Patterns

| Element | Behavior |
|---|---|
| Button | `activeOpacity={0.8}`, translucent background |
| FAB | White circle (`#FFFFFF`), black `+` icon, `activeOpacity={0.85}` |
| Bottom sheet | `Modal animationType="slide"`, `borderTopRadius 28px`, `bgMid` background |
| Overlay | `rgba(0,0,0,0.40)` backdrop behind sheet |
| Sheet handle | 56px wide, 6px tall, `rgba(255,255,255,0.15)`, centered |

---

## Screen Composition Order

Every new screen must follow this structure:

```tsx
<ZenScreen scrollable={true|false}>
  {/* 1. Header */}
  <View> eyebrow + title + optional right button </View>

  {/* 2. Optional toggle/filter row */}

  {/* 3. Content blocks — SurfaceCard / SectionCard */}
  <SurfaceCard>
    <SectionEyebrow>Section Title</SectionEyebrow>
    {/* content */}
  </SurfaceCard>

  {/* 4. Optional FAB (position: absolute, bottom: 28, right: 0) */}

  {/* 5. No BottomTabNav — handled by AppNavigator */}
</ZenScreen>
```

**Never** add `BottomTabNav` inside screens — it is rendered by `AppNavigator.tsx`.

---

## Navigation Structure

```
AppNavigator (BottomTab)
├── TodayTab     → HomeScreen
├── PlanTab      → PlanScreen → CompletedActivityDetailScreen
├── CoachTab     → CoachScreen
└── HistoryTab   → HistoryScreen → StressDetail, RecoveryDetail,
                                   ReadinessOverlay, Archetype,
                                   Journey, ReportCard, Settings
```

---

## Score Ring Usage

```tsx
// stroke is number (default 8), size is number (default 120)
// color prop sets the arc color
<ScoreRing score={74} color={ZEN.colors.recovery} size={128} stroke={9} />
```

- Stress ring color: `ZEN.colors.stress`
- Recovery ring color: `ZEN.colors.recovery`
- Readiness ring color: `ZEN.colors.readiness`

---

## FAB Standard

```tsx
// White FAB — always position absolute, bottom-right
style={{
  position: 'absolute', bottom: 28, right: 0,
  width: 64, height: 64, borderRadius: 32,
  backgroundColor: '#FFFFFF',
  alignItems: 'center', justifyContent: 'center',
  shadowColor: '#000', shadowOffset: { width: 0, height: 6 },
  shadowOpacity: 0.30, shadowRadius: 12, elevation: 8, zIndex: 99,
}}
// Label: <Text style={{ fontSize: 32, color: '#000', lineHeight: 36 }}>+</Text>
```

---

## Brand Aesthetic

Target feel: **Whoop · Oura · Levels**

- Premium, calm, dark, minimal
- No heavy gradients on UI elements (only background)
- No colored backgrounds on cards (dark translucent only)
- No drop shadows on cards (border-only definition)
- Subtle, purposeful use of color (only on data/scores)
- All motion: subtle, no bounce or spring animations

---

## File Reference

| File | Role |
|---|---|
| `src/ui/zenflow-ui-kit.tsx` | All reusable components + ZEN constants |
| `src/navigation/AppNavigator.tsx` | Tab + stack navigation |
| `src/api/endpoints.ts` | All API calls |
| `src/types/index.ts` | Shared TypeScript types |
| `src/hooks/` | Data hooks (`usePlan`, `useCoach`, etc.) |
