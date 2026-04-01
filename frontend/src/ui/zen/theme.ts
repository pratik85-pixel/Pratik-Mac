export const ZEN = {
  colors: {
    /** Screen background top */
    bgTop:   '#132235',
    /** Screen background mid */
    bgMid:   '#0A111A',
    /** Screen background bottom */
    bgBottom: '#05090E',
    /** Card surface: bg-white/[0.03] */
    surface:     'rgba(255,255,255,0.03)',
    /** Soft surface: bg-white/[0.025] */
    surfaceSoft: 'rgba(255,255,255,0.025)',
    /** Strong surface: bg-white/[0.045] */
    surfaceStrong: 'rgba(255,255,255,0.045)',
    /** Default border: border-white/8 */
    border:       'rgba(255,255,255,0.08)',
    /** Strong border: border-white/10 */
    borderStrong: 'rgba(255,255,255,0.10)',
    /** text-white/94 */
    textPrimary:   'rgba(255,255,255,0.94)',
    /** text-white/88 */
    textBody:      'rgba(255,255,255,0.88)',
    /** text-white/58 */
    textSecondary: 'rgba(255,255,255,0.58)',
    /** text-white/55 */
    textLabel:     'rgba(255,255,255,0.55)',
    /** text-white/52 */
    textSubtle:    'rgba(255,255,255,0.52)',
    /** text-white/50 */
    textHalf:      'rgba(255,255,255,0.50)',
    /** text-white/48 */
    textFaint:     'rgba(255,255,255,0.48)',
    /** text-white/45 */
    textMuted:     'rgba(255,255,255,0.45)',
    /** text-white/42 */
    textQuiet:     'rgba(255,255,255,0.42)',
    /** text-white/40 */
    textDim:       'rgba(255,255,255,0.40)',
    /** text-white/38 */
    textGhost:     'rgba(255,255,255,0.38)',
    /** text-white/90 */
    textNear:      'rgba(255,255,255,0.90)',
    /** text-white/92 */
    textAlmost:    'rgba(255,255,255,0.92)',
    /** text-white/75 */
    textSoft:      'rgba(255,255,255,0.75)',
    /** text-white/84 */
    textWarm:      'rgba(255,255,255,0.84)',
    /** #19B5FE — stress */
    stress:    '#19B5FE',
    /** #39E27D — recovery */
    recovery:  '#39E27D',
    /** #F2D14C — readiness */
    readiness: '#F2D14C',
    /** white */
    white: '#FFFFFF',
    /** transparent border active tab */
    tabActiveBorder: 'rgba(255,255,255,0.18)',
    /** bg active tab */
    tabActiveBg: 'rgba(255,255,255,0.08)',
    /** #8EDBFF — stress tag CTA text */
    stressTagText: '#8EDBFF',
    /** rgba(25,181,254,0.30) — stress tag CTA border */
    stressTagBorder: 'rgba(25,181,254,0.30)',
    /** rgba(25,181,254,0.10) — stress tag CTA bg */
    stressTagBg: 'rgba(25,181,254,0.10)',
    /** rgba(25,181,254,0.14) — chart point glow ring */
    stressGlowRing: 'rgba(25,181,254,0.14)',
    /** rgba(25,181,254,0.28) — chart area top */
    stressAreaTop: 'rgba(25,181,254,0.28)',
    /** rgba(255,255,255,0.08) — chart grid lines */
    chartGrid: 'rgba(255,255,255,0.08)',
    /** rgba(255,255,255,0.14) — chart vertical marker */
    chartMarker: 'rgba(255,255,255,0.14)',
    /** rgba(255,255,255,0.15) — sheet drag handle */
    dragHandle: 'rgba(255,255,255,0.15)',
  },
  radius: {
    /** rounded-[34px] — screen shell */
    screen:  34,
    /** rounded-[30px] — section card */
    section: 30,
    /** rounded-[24px] — card */
    card:    24,
    /** rounded-[22px] — chart inner */
    chart:   22,
    /** rounded-[20px] — button */
    button:  20,
    /** rounded-[18px] — tab item */
    tab:     18,
    /** rounded-full */
    pill:    9999,
  },
} as const;

