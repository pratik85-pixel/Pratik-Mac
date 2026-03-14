import React, { ReactNode } from 'react';

// ─── Theme ────────────────────────────────────────────────────────────────────

const theme = {
  colors: {
    bgTop: "#132235",
    bgMid: "#0A111A",
    bgBottom: "#05090E",
    surface: "bg-white/[0.03]",
    surfaceSoft: "bg-white/[0.025]",
    surfaceStrong: "bg-white/[0.045]",
    border: "border-white/8",
    borderStrong: "border-white/10",
    textPrimary: "text-white/94",
    textBody: "text-white/88",
    textSecondary: "text-white/58",
    textMuted: "text-white/45",
    textQuiet: "text-white/42",
    stress: "#19B5FE",
    recovery: "#39E27D",
    readiness: "#F2D14C",
  },
  radius: {
    screen: "rounded-[34px]",
    section: "rounded-[30px]",
    card: "rounded-[24px]",
    button: "rounded-[20px]",
    pill: "rounded-full",
  },
};

const sampleScores = [
  {
    label: "Stress",
    value: 32,
    suffix: "",
    progress: 0.32,
    color: theme.colors.stress,
    subtext: "Calm today",
  },
  {
    label: "Recovery",
    value: 81,
    suffix: "%",
    progress: 0.81,
    color: theme.colors.recovery,
    subtext: "Recovered well",
  },
  {
    label: "Readiness",
    value: 74,
    suffix: "",
    progress: 0.74,
    color: theme.colors.readiness,
    subtext: "Strong start",
  },
];

const sampleInsights = [
  {
    eyebrow: "What matters",
    title: "Recovery is carrying you today",
    body: "Sleep and downtime restored enough capacity to take on a moderate load without drifting into overload.",
  },
  {
    eyebrow: "Recommended tone",
    title: "Build momentum, not pressure",
    body: "Aim for a steady day with one meaningful effort block and one deliberate recovery window later in the evening.",
  },
];

// ─── Prop Interfaces ─────────────────────────────────────────────────────────

export interface MobileShellProps {
  children: ReactNode;
}

export interface TopHeaderProps {
  eyebrow: string;
  title: string;
  subtitle: string;
  leftIcon: ReactNode;
  rightIcon: ReactNode;
}

export interface IconButtonProps {
  children: ReactNode;
  small?: boolean;
}

export interface SectionCardProps {
  children: ReactNode;
  className?: string;
}

export interface SurfaceCardProps {
  children: ReactNode;
  className?: string;
}

export interface SectionEyebrowProps {
  children: ReactNode;
}

export interface ScoreTileProps {
  label: string;
  value: number;
  suffix: string;
  progress: number;
  color: string;
  subtext: string;
}

export interface ScoreRingProps {
  value: number;
  suffix: string;
  progress: number;
  color: string;
  size?: number;
  stroke?: number;
}

export interface CoachSummaryProps {
  title: string;
  body: string;
}

export interface PrimaryButtonProps {
  eyebrow: string;
  label: string;
  rightIcon?: ReactNode;
}

export interface InfoCardProps {
  eyebrow: string;
  title: string;
  body: string;
}

export interface NavItemProps {
  label: string;
  icon: ReactNode;
  active?: boolean;
}

export interface BottomTabNavProps {
  items: NavItemProps[];
}

// ─── Screens & Components ─────────────────────────────────────────────────────

export default function ZenFlowHomeScreen() {
  return (
    <MobileShell>
      <div className="relative z-10 flex min-h-[844px] flex-col px-5 pb-6 pt-4">
        <TopHeader
          eyebrow="Tue, Jun 27"
          title="Today"
          subtitle="Good morning"
          leftIcon="‹"
          rightIcon="⚙"
        />

        <SectionCard className="px-4 pb-5 pt-5">
          <div className="grid grid-cols-3 gap-3">
            {sampleScores.map((score) => (
              <ScoreTile key={score.label} {...score} />
            ))}
          </div>

          <CoachSummary
            title="Coach synthesis"
            body="Your body absorbed yesterday’s load well. Recovery stayed strong overnight, and your stress load is low enough to push into the day with confidence."
          />

          <PrimaryButton eyebrow="Plan" label="See today’s plan" />
        </SectionCard>

        <section className="mt-5 grid gap-3">
          {sampleInsights.map((item) => (
            <InfoCard key={item.title} {...item} />
          ))}
        </section>

        <div className="mt-auto pt-6">
          <BottomTabNav
            items={[
              { label: "Home", icon: "⌂", active: true },
              { label: "Plan", icon: "◫" },
              { label: "Coach", icon: "◎" },
              { label: "History", icon: "≡" },
            ]}
          />
        </div>
      </div>
    </MobileShell>
  );
}

export function MobileShell({ children }: MobileShellProps) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#132235_0%,_#0A111A_42%,_#05090E_100%)] text-white flex items-center justify-center p-4">
      <div
        className={`relative w-full max-w-[390px] min-h-[844px] overflow-hidden ${theme.radius.screen} border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.02)_0%,rgba(255,255,255,0.01)_100%)] shadow-2xl`}
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.08),_transparent_36%),radial-gradient(circle_at_80%_20%,_rgba(59,130,246,0.06),_transparent_28%)]" />
        {children}
      </div>
    </div>
  );
}

export function TopHeader({ eyebrow, title, subtitle, leftIcon, rightIcon }: TopHeaderProps) {
  return (
    <header className="pt-2">
      <div className="mb-5 flex items-center justify-between text-white/90">
        <IconButton>{leftIcon}</IconButton>

        <div className="text-center">
          <div className="text-[11px] uppercase tracking-[0.32em] text-white/50">{eyebrow}</div>
          <div className="mt-1 text-sm font-medium text-white/90">{subtitle}</div>
        </div>

        <IconButton small>{rightIcon}</IconButton>
      </div>

      <div className="mb-4">
        <SectionEyebrow>Overview</SectionEyebrow>
        <h1 className="mt-2 text-[34px] font-semibold tracking-[-0.03em] text-white">{title}</h1>
      </div>
    </header>
  );
}

export function IconButton({ children, small = false }: IconButtonProps) {
  return (
    <button className="flex h-10 w-10 items-center justify-center rounded-full border border-white/15 bg-white/5 backdrop-blur-sm transition-transform duration-200 hover:scale-[0.98]">
      <span className={small ? "text-sm" : "text-lg"}>{children}</span>
    </button>
  );
}

export function SectionCard({ children, className = "" }: SectionCardProps) {
  return (
    <section
      className={`${theme.radius.section} border ${theme.colors.border} ${theme.colors.surface} backdrop-blur-xl ${className}`}
    >
      {children}
    </section>
  );
}

export function SurfaceCard({ children, className = "" }: SurfaceCardProps) {
  return (
    <div
      className={`${theme.radius.card} border ${theme.colors.border} ${theme.colors.surfaceSoft} backdrop-blur-xl ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionEyebrow({ children }: SectionEyebrowProps) {
  return <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">{children}</div>;
}

export function ScoreTile({ label, value, suffix, progress, color, subtext }: ScoreTileProps) {
  return (
    <button className="group rounded-[24px] border border-white/8 bg-white/[0.025] p-3 text-left transition duration-200 hover:border-white/15 hover:bg-white/[0.04]">
      <div className="flex justify-center">
        <ScoreRing value={value} suffix={suffix} progress={progress} color={color} />
      </div>
      <div className="mt-3 text-center">
        <div className="text-[11px] uppercase tracking-[0.22em] text-white/55">{label}</div>
        <div className="mt-1 text-[11px] text-white/45">{subtext}</div>
      </div>
    </button>
  );
}

export function ScoreRing({ value, suffix, progress, color, size = 92, stroke = 7 }: ScoreRingProps) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * 0.82;
  const gap = circumference - dash;
  const offset = dash * (1 - progress);

  return (
    <div className="relative flex items-center justify-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-[126deg]">
        <defs>
          <filter id={`glow-${color.replace("#", "")}`} x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="0" stdDeviation="2" floodColor={color} floodOpacity="0.28" />
          </filter>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.10)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${gap}`}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${gap}`}
          strokeDashoffset={offset}
          filter={`url(#glow-${color.replace("#", "")})`}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-[26px] font-semibold tracking-[-0.04em] text-white">
          {value}
          <span className="text-[12px] align-[5px] text-white/55">{suffix}</span>
        </div>
      </div>
    </div>
  );
}

export function CoachSummary({ title, body }: CoachSummaryProps) {
  return (
    <SurfaceCard className="mt-5 p-4">
      <SectionEyebrow>{title}</SectionEyebrow>
      <p className="mt-3 text-[16px] leading-7 text-white/88">{body}</p>
    </SurfaceCard>
  );
}

export function PrimaryButton({ eyebrow, label, rightIcon = "→" }: PrimaryButtonProps) {
  return (
    <button className="mt-4 flex h-14 w-full items-center justify-between rounded-[20px] border border-white/10 bg-white/[0.045] px-5 text-left transition duration-200 hover:bg-white/[0.06]">
      <div>
        <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">{eyebrow}</div>
        <div className="mt-1 text-[16px] font-medium text-white/92">{label}</div>
      </div>
      <span className="text-xl text-white/75">{rightIcon}</span>
    </button>
  );
}

export function InfoCard({ eyebrow, title, body }: InfoCardProps) {
  return (
    <div className="rounded-[24px] border border-white/8 bg-white/[0.03] p-4 backdrop-blur-xl">
      <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">{eyebrow}</div>
      <div className="mt-2 text-[18px] font-medium tracking-[-0.02em] text-white/94">{title}</div>
      <p className="mt-2 text-[14px] leading-6 text-white/58">{body}</p>
    </div>
  );
}

export function BottomTabNav({ items }: BottomTabNavProps) {
  return (
    <nav className="grid grid-cols-4 rounded-[24px] border border-white/10 bg-white/[0.04] px-2 py-2 backdrop-blur-xl">
      {items.map((item) => (
        <NavItem key={item.label} {...item} />
      ))}
    </nav>
  );
}

export function NavItem({ label, icon, active = false }: NavItemProps) {
  return (
    <button className="flex flex-col items-center justify-center gap-1 rounded-[18px] py-2 text-center transition duration-200 hover:bg-white/[0.04]">
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-full border text-sm ${
          active
            ? "border-white/18 bg-white/[0.08] text-white"
            : "border-transparent bg-transparent text-white/45"
        }`}
      >
        {icon}
      </div>
      <div className={active ? "text-[11px] text-white/88" : "text-[11px] text-white/42"}>{label}</div>
    </button>
  );
}

/*
COPY/PASTE PROMPT FOR VS CODE AI

Use this file as the exact visual and component reference for all future ZenFlow screens.

Rules:
1. Do not invent a new design system.
2. Reuse these existing components and styling patterns exactly:
   - MobileShell
   - TopHeader
   - SectionCard
   - SurfaceCard
   - SectionEyebrow
   - ScoreRing
   - CoachSummary
   - PrimaryButton
   - InfoCard
   - BottomTabNav
   - NavItem
3. Match the same:
   - spacing rhythm
   - dark gradient background
   - border opacity
   - card opacity
   - rounded corners
   - typography scale
   - uppercase tracked labels
   - muted premium color palette
4. New screens must feel like they belong to this exact app.
5. Do not introduce bright colors, generic dashboard cards, thick shadows, or mismatched typography.
6. If a new component is needed, build it by extending the visual language already defined here.

When building a new screen, start from this file and keep the UI consistent.
*/