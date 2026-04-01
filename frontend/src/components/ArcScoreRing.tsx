/**
 * ArcScoreRing — Whoop-style 270° SVG arc gauge.
 *
 * The arc spans from lower-left (225° CW from 12 o'clock) to lower-right
 * (135° CW from 12 o'clock), leaving a small gap at the bottom. The filled
 * portion is proportional to the score (0–100).
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { Colors } from '../theme';

interface ArcScoreRingProps {
  variant: 'stress' | 'recovery' | 'readiness';
  value: number | null;
  /** Outer diameter of the ring (default 110) */
  size?: number;
  /** Stroke thickness (default 11) */
  strokeWidth?: number;
  label: string;
  sub?: string;
  onPress?: () => void;
  isEstimated?: boolean;
}

const PALETTE = {
  stress:    { fill: Colors.stress,    track: Colors.stressDim },
  recovery:  { fill: Colors.recovery,  track: Colors.recoveryDim },
  readiness: { fill: Colors.readiness, track: Colors.readinessDim },
};

// Arc geometry
const START_ANGLE = 225;   // degrees CW from 12 o'clock (lower-left)
const TOTAL_ARC   = 270;   // total sweep in degrees

/** Convert from "CW degrees from 12 o'clock" to SVG x,y */
function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number,
): { x: number; y: number } {
  // Subtract 90 to rotate origin from 3 o'clock to 12 o'clock
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** Build an SVG arc path between two angles */
function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string {
  const s = polarToCartesian(cx, cy, r, startAngle);
  const e = polarToCartesian(cx, cy, r, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return (
    `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} ` +
    `A ${r} ${r} 0 ${largeArc} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`
  );
}

export default function ArcScoreRing({
  variant,
  value,
  size = 110,
  strokeWidth = 11,
  label,
  sub,
  onPress,
  isEstimated = false,
}: ArcScoreRingProps) {
  const { fill, track } = PALETTE[variant];
  const cx = size / 2;
  const cy = size / 2;
  const r  = (size - strokeWidth) / 2;

  // Background track — full 270°
  const trackD = arcPath(cx, cy, r, START_ANGLE, START_ANGLE + TOTAL_ARC);

  // Filled arc — proportional to value
  const clamped = value != null ? Math.max(1, Math.min(100, value)) : 0;
  const fillDeg = (clamped / 100) * TOTAL_ARC;
  const fillD   = value != null && value > 0
    ? arcPath(cx, cy, r, START_ANGLE, START_ANGLE + fillDeg)
    : null;

  const display = value != null ? String(Math.round(value)) : '—';

  const ringContent = (
    <View style={styles.ringWrap}>
      {/* SVG ring */}
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size}>
          {/* Track */}
          <Path
            d={trackD}
            stroke={track}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            fill="none"
          />
          {/* Filled arc */}
          {fillD && (
            <Path
              d={fillD}
              stroke={fill}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              fill="none"
            />
          )}
        </Svg>

        {/* Value + estimated badge centred over the ring */}
        <View style={[StyleSheet.absoluteFill, styles.centerContent]} pointerEvents="none">
          <Text style={[styles.valueText, { color: fill }]}>{display}</Text>
          {isEstimated && (
            <Text style={[styles.estBadge, { color: fill }]}>est</Text>
          )}
        </View>
      </View>

      {/* Label below ring */}
      <Text style={styles.label}>{label}</Text>
      {sub ? <Text style={styles.sub}>{sub}</Text> : null}
    </View>
  );

  if (onPress) {
    return (
      <TouchableOpacity
        onPress={onPress}
        activeOpacity={0.75}
        style={styles.touchable}
      >
        {ringContent}
      </TouchableOpacity>
    );
  }

  return ringContent;
}

const styles = StyleSheet.create({
  touchable: { flex: 1 },
  ringWrap: { alignItems: 'center', gap: 6, flex: 1 },
  centerContent: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  valueText: {
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -1,
    lineHeight: 32,
  },
  estBadge: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    opacity: 0.65,
    marginTop: 1,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  sub: {
    fontSize: 10,
    color: Colors.textMuted,
    textAlign: 'center',
  },
});
