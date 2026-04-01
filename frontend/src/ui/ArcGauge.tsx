import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { ZEN } from './zenflow-ui-kit';

function polar(cx: number, cy: number, r: number, deg: number): { x: number; y: number } {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

export function ArcGauge({
  value,
  color,
  size,
  stroke,
  goal,
  valueFontSize,
  displayValue,
  displaySuffix,
}: {
  value: number | null;
  color: string;
  size: number;
  stroke: number;
  goal?: number | null;
  valueFontSize?: number;
  displayValue?: string | null;
  displaySuffix?: string;
}) {
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const progressOffset = c * (1 - v / 100);
  const g = goal == null ? null : Math.max(0, Math.min(100, goal));
  const goalPoint = g == null ? null : polar(cx, cy, r, -90 + g * 3.6);

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <Circle
          cx={cx}
          cy={cy}
          r={r}
          stroke="rgba(255,255,255,0.10)"
          strokeWidth={stroke}
          fill="none"
        />
        <Circle
          cx={cx}
          cy={cy}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={`${c}`}
          strokeDashoffset={progressOffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        {goalPoint ? (
          <Circle cx={goalPoint.x} cy={goalPoint.y} r={4} fill={ZEN.colors.white} />
        ) : null}
      </Svg>
      <View style={[StyleSheet.absoluteFillObject, { alignItems: 'center', justifyContent: 'center' }]}>
        <Text style={{ color: ZEN.colors.white, fontWeight: '800', fontSize: valueFontSize ?? (size > 120 ? 34 : 20) }}>
          {displayValue ?? (value == null ? '—' : `${Math.round(v)}%`)}
          {displaySuffix ? (
            <Text style={{ fontSize: Math.max(10, (valueFontSize ?? (size > 120 ? 34 : 20)) * 0.45), color: ZEN.colors.textMuted }}>
              {displaySuffix}
            </Text>
          ) : null}
        </Text>
      </View>
    </View>
  );
}
