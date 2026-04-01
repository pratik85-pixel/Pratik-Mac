/**
 * DayGauge — 180° speedometer-style gauge using SVG.
 *
 * Displays a score on a colour-graded semicircular arc with a white needle,
 * a large numeric label, and a LOW / MEDIUM / HIGH descriptor.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Path, Line, Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import { Colors } from '../theme';

interface DayGaugeProps {
  /** Current score value */
  score: number | null;
  /** Max value of the scale (default 10) */
  max?: number;
  /** 'stress' tints track red at high end; 'recovery' tints green at high end */
  variant: 'stress' | 'recovery';
  /** Optional label e.g. "Last updated at: 15:32" */
  subLabel?: string;
}

// ── Geometry ──────────────────────────────────────────────────────────────────
const W = 300;
const H = 170;
const CX = 150;
const CY = 148;   // centre sits near bottom so arc appears correctly
const R_OUTER = 108;
const R_INNER = 78;
const R_NEEDLE = 96;

/** Convert a 0–1 fraction to an SVG arc path point on CX/CY/r */
function pct2xy(fraction: number, r: number) {
  // 0 → left (180°),  1 → right (0°)
  const angleDeg = 180 - fraction * 180;
  const rad = (angleDeg * Math.PI) / 180;
  return {
    x: CX + r * Math.cos(rad),
    y: CY - r * Math.sin(rad),
  };
}

/** Build a donut-arc SVG path for a fraction band [f0, f1] */
function arcBand(f0: number, f1: number): string {
  const o0 = pct2xy(f0, R_OUTER);
  const o1 = pct2xy(f1, R_OUTER);
  const i0 = pct2xy(f0, R_INNER);
  const i1 = pct2xy(f1, R_INNER);
  const large = f1 - f0 > 0.5 ? 1 : 0;
  return [
    `M ${o0.x.toFixed(2)} ${o0.y.toFixed(2)}`,
    `A ${R_OUTER} ${R_OUTER} 0 ${large} 0 ${o1.x.toFixed(2)} ${o1.y.toFixed(2)}`,
    `L ${i1.x.toFixed(2)} ${i1.y.toFixed(2)}`,
    `A ${R_INNER} ${R_INNER} 0 ${large} 1 ${i0.x.toFixed(2)} ${i0.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

// ── Colour bands ──────────────────────────────────────────────────────────────

const STRESS_BANDS = [
  { f: [0.00, 0.25] as [number, number], color: '#2D9CDB' },  // blue
  { f: [0.25, 0.50] as [number, number], color: '#34C759' },  // green
  { f: [0.50, 0.72] as [number, number], color: '#F2C94C' },  // yellow
  { f: [0.72, 0.88] as [number, number], color: '#FF9500' },  // orange
  { f: [0.88, 1.00] as [number, number], color: '#FF3B30' },  // red
];

const RECOVERY_BANDS = [
  { f: [0.00, 0.20] as [number, number], color: '#FF3B30' },  // red (low)
  { f: [0.20, 0.45] as [number, number], color: '#FF9500' },  // orange
  { f: [0.45, 0.65] as [number, number], color: '#F2C94C' },  // yellow
  { f: [0.65, 0.82] as [number, number], color: '#34C759' },  // green
  { f: [0.82, 1.00] as [number, number], color: '#30D158' },  // bright green
];

// ── Descriptor helper ─────────────────────────────────────────────────────────

function descriptor(score: number, max: number, variant: 'stress' | 'recovery'): string {
  const pct = score / max;
  if (variant === 'stress') {
    if (pct < 0.30) return 'LOW';
    if (pct < 0.65) return 'MEDIUM';
    return 'HIGH';
  } else {
    if (pct < 0.30) return 'LOW';
    if (pct < 0.65) return 'MODERATE';
    return 'GOOD';
  }
}

function descriptorColor(desc: string): string {
  if (desc === 'LOW') return '#34C759';
  if (desc === 'MODERATE' || desc === 'MEDIUM') return '#F2C94C';
  if (desc === 'GOOD') return '#34C759';
  return '#FF3B30';
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DayGauge({ score, max = 10, variant, subLabel }: DayGaugeProps) {
  const safeScore = score ?? 0;
  const fraction = Math.min(1, Math.max(0, safeScore / max));
  const bands = variant === 'stress' ? STRESS_BANDS : RECOVERY_BANDS;

  // Needle line endpoint
  const needleTip = pct2xy(fraction, R_NEEDLE);
  const needleBase0 = pct2xy(fraction - 0.015, R_INNER - 8);
  const needleBase1 = pct2xy(fraction + 0.015, R_INNER - 8);

  const desc = descriptor(safeScore, max, variant);
  const descColor = descriptorColor(desc);

  // Min/max axis labels
  const leftLabel = '0.0';
  const rightLabel = max.toFixed(1);

  return (
    <View style={styles.container}>
      <Svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* Track background */}
        <Path
          d={arcBand(0, 1)}
          fill="#1E1E24"
        />

        {/* Coloured bands */}
        {bands.map((b, i) => (
          <Path key={i} d={arcBand(b.f[0], b.f[1])} fill={b.color} opacity={0.85} />
        ))}

        {/* Dark overlay beyond score (dims the unused arc) */}
        {fraction < 1 && (
          <Path
            d={arcBand(fraction, 1)}
            fill="#0A0A0C"
            opacity={0.65}
          />
        )}

        {/* Needle */}
        <Line
          x1={CX}
          y1={CY}
          x2={needleTip.x.toFixed(2)}
          y2={needleTip.y.toFixed(2)}
          stroke="#FFFFFF"
          strokeWidth={3}
          strokeLinecap="round"
        />
        <Circle cx={CX} cy={CY} r={7} fill="#FFFFFF" />
        <Circle cx={CX} cy={CY} r={3} fill="#0A0A0C" />
      </Svg>

      {/* Axis labels */}
      <View style={styles.axisRow}>
        <Text style={styles.axisLabel}>{leftLabel}</Text>
        <Text style={styles.axisLabel}>{rightLabel}</Text>
      </View>

      {/* Score + descriptor */}
      <View style={styles.scoreBlock}>
        <Text style={styles.scoreNum}>
          {safeScore === 0 ? '—' : safeScore.toFixed(1)}
        </Text>
        {score !== null && (
          <Text style={[styles.descriptor, { color: descColor }]}>{desc}</Text>
        )}
        {subLabel ? (
          <Text style={styles.subLabel}>{subLabel}</Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    width: '100%',
    marginTop: -8,
  },
  axisRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: W * 0.86,
    marginTop: -20,
  },
  axisLabel: {
    fontSize: 12,
    color: '#555',
    fontWeight: '500',
  },
  scoreBlock: {
    alignItems: 'center',
    marginTop: -80,
    marginBottom: 8,
  },
  scoreNum: {
    fontSize: 52,
    fontWeight: '700',
    color: '#FFFFFF',
    letterSpacing: -2,
    lineHeight: 58,
  },
  descriptor: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    marginTop: 2,
  },
  subLabel: {
    fontSize: 11,
    color: '#555',
    marginTop: 4,
    letterSpacing: 0.2,
  },
});
