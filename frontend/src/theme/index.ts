// ZenFlow Verity — Design tokens
// WHOOP-inspired: pure black ground, data glows on darkness

export const Colors = {
  // Ground
  black:       '#000000',
  surface0:    '#0A0A0A',
  surface1:    '#111111',
  surface2:    '#1A1A1A',
  surface3:    '#222222',
  border:      '#2A2A2A',
  borderFaint: '#1C1C1C',

  // Text
  text:          '#FFFFFF',   // alias for textPrimary
  textPrimary:   '#FFFFFF',
  textSecondary: '#8C8C8C',
  textMuted:     '#4A4A4A',
  textInverse:   '#000000',

  // Semantic — the three daily numbers
  stress:      '#FF3B30',   // red  — stress load
  stressLight: '#FF6B6B',
  stressDim:   '#3D1A18',
  recovery:    '#34C759',   // green — recovery
  recoveryLight:'#5ED87A',
  recoveryDim: '#0F2E18',
  readiness:   '#0A84FF',   // blue  — readiness
  readinessLight:'#4AA3FF',
  readinessDim:'#0A1F3D',

  // Zones (session coherence)
  zone1: '#6B6B6B',   // Settling   — grey
  zone2: '#4A90D9',   // Finding it — soft blue
  zone3: '#34C759',   // In Sync    — green
  zone4: '#FFD60A',   // Flow       — gold

  // Coach / plan
  coach:     '#AF52DE',
  coachDim:  '#25103A',
  amber:     '#FF9500',
  amberDim:  '#3D2500',

  // Priority badges
  mustDo:      '#FF9500',
  recommended: '#34C759',
  optional:    '#8C8C8C',
};

export const Typography = {
  // Hero numbers — the three big scores
  hero: {
    fontSize: 64,
    fontWeight: '700' as const,
    letterSpacing: -2,
    color: Colors.textPrimary,
  },
  heroMedium: {
    fontSize: 48,
    fontWeight: '700' as const,
    letterSpacing: -1.5,
    color: Colors.textPrimary,
  },
  heroSmall: {
    fontSize: 36,
    fontWeight: '700' as const,
    letterSpacing: -1,
    color: Colors.textPrimary,
  },

  // Section labels — uppercase, tracked
  label: {
    fontSize: 11,
    fontWeight: '600' as const,
    letterSpacing: 1.2,
    textTransform: 'uppercase' as const,
    color: Colors.textSecondary,
  },
  labelSmall: {
    fontSize: 10,
    fontWeight: '600' as const,
    letterSpacing: 1.0,
    textTransform: 'uppercase' as const,
    color: Colors.textMuted,
  },

  // Body
  body: {
    fontSize: 15,
    fontWeight: '400' as const,
    lineHeight: 22,
    color: Colors.textPrimary,
  },
  bodySmall: {
    fontSize: 13,
    fontWeight: '400' as const,
    lineHeight: 19,
    color: Colors.textSecondary,
  },

  // Headings
  title: {
    fontSize: 22,
    fontWeight: '700' as const,
    letterSpacing: -0.5,
    color: Colors.textPrimary,
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '600' as const,
    letterSpacing: -0.3,
    color: Colors.textPrimary,
  },

  // Coach synthesis sentence
  synthesis: {
    fontSize: 16,
    fontWeight: '400' as const,
    lineHeight: 24,
    color: Colors.textSecondary,
    fontStyle: 'italic' as const,
  },
};

export const Spacing = {
  xs:  4,
  sm:  8,
  md:  16,
  lg:  24,
  xl:  32,
  xxl: 48,
};

export const Radius = {
  sm:  8,
  md:  12,
  lg:  16,
  xl:  24,
  full: 999,
};

export const Shadows = {
  // Subtle glow on dark cards — never harsh
  card: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.6,
    shadowRadius: 4,
    elevation: 3,
  },
  stress: {
    shadowColor: Colors.stress,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
    elevation: 5,
  },
  recovery: {
    shadowColor: Colors.recovery,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
    elevation: 5,
  },
  readiness: {
    shadowColor: Colors.readiness,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 12,
    elevation: 5,
  },
};
