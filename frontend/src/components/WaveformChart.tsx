/**
 * WaveformChart — full-day time-series chart.
 *
 * Shows the complete day from the first data point to the current time.
 * Features:
 *  • Colour-graded line (green→yellow→orange) based on value
 *  • Dark background with horizontal grid lines + axis labels
 *  • Sleep / rest region shading (grey translucent band)
 *  • Vertical dashed "now" marker
 *  • Vertical highlight lines at stress/recovery event peaks (passed as events prop)
 */
import React, { useMemo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, {
  Path, Line, Rect, Text as SvgText,
  Defs, LinearGradient, Stop, Circle,
} from 'react-native-svg';
import { Colors } from '../theme';
import type { WaveformPoint, StressWindow, RecoveryWindow } from '../types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface WaveformChartProps {
  points: WaveformPoint[];
  personalAvg?: number;
  variant: 'stress' | 'recovery' | 'overlay';
  height?: number;
  /** Pass stress/recovery windows so peak moments can be marked on the chart */
  events?: (StressWindow | RecoveryWindow)[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const SVG_W = 360;
const PADDING_LEFT  = 36;   // y-axis labels
const PADDING_RIGHT = 12;
const PADDING_TOP   = 12;
const PADDING_BOTTOM = 28;  // x-axis labels

// ── Helpers ───────────────────────────────────────────────────────────────────

function isoToMinutes(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function formatHHMM(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60) % 24;
  const m = totalMinutes % 60;
  return `${h}:${m.toString().padStart(2, '0')}`;
}

function stressFromRMSSD(rmssd: number, minR: number, maxR: number): number {
  // Invert: low RMSSD → high stress. Scale to 0-3.
  const range = maxR - minR || 1;
  return ((maxR - rmssd) / range) * 3;
}

function recoveryFromRMSSD(rmssd: number, minR: number, maxR: number): number {
  const range = maxR - minR || 1;
  return ((rmssd - minR) / range) * 3;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function WaveformChart({
  points,
  personalAvg,
  variant,
  height = 200,
  events = [],
}: WaveformChartProps) {
  const chartH = height - PADDING_TOP - PADDING_BOTTOM;
  const chartW = SVG_W - PADDING_LEFT - PADDING_RIGHT;

  // IMPORTANT: do not early-return before calling hooks. React requires the same
  // number and order of hooks on every render — returning above `useMemo` when
  // `points.length` crosses the threshold causes runtime corruption.
  const derived = useMemo(() => {
    if (!points || points.length < 2) {
      return { kind: 'empty' as const, reason: 'no-data' as const };
    }
    const valid = points.filter((p) => p.rmssd_ms && p.rmssd_ms > 0 && p.window_start);
    if (valid.length < 2) {
      return { kind: 'empty' as const, reason: 'invalid' as const };
    }

    // Single-pass min/max (avoid Math.min(...arr) / Math.max(...arr) for large arrays)
    let minR = Number.POSITIVE_INFINITY;
    let maxR = Number.NEGATIVE_INFINITY;
    for (const p of valid) {
      const r = Number(p.rmssd_ms);
      if (!Number.isFinite(r)) continue;
      if (r < minR) minR = r;
      if (r > maxR) maxR = r;
    }
    if (!Number.isFinite(minR) || !Number.isFinite(maxR)) {
      return { kind: 'empty' as const };
    }

    const isStress = variant === 'stress';
    const toMetric = (r: number) =>
      isStress ? stressFromRMSSD(r, minR, maxR) : recoveryFromRMSSD(r, minR, maxR);

    const dayMinutes = valid.map((p) => isoToMinutes(p.window_start));
    const nowMinutes = new Date().getHours() * 60 + new Date().getMinutes();
    const minMin = Math.max(0, Math.min(...dayMinutes) - 10);
    const maxMin = Math.min(1440, Math.max(...dayMinutes, nowMinutes) + 10);
    const timeRange = maxMin - minMin || 60;

    const toX = (minutes: number) =>
      PADDING_LEFT + ((minutes - minMin) / timeRange) * chartW;
    const toY = (metric: number) =>
      PADDING_TOP + (1 - Math.min(1, Math.max(0, metric / 3))) * chartH;

    const mapped = valid.map((p) => ({
      x: toX(isoToMinutes(p.window_start)),
      y: toY(toMetric(p.rmssd_ms as number)),
      isSleep: p.context === 'sleep' || p.context?.includes('sleep'),
    }));

    const linePath = mapped
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(' ');

    const areaPath =
      linePath +
      ` L ${mapped[mapped.length - 1].x.toFixed(1)} ${(PADDING_TOP + chartH).toFixed(1)}` +
      ` L ${mapped[0].x.toFixed(1)} ${(PADDING_TOP + chartH).toFixed(1)} Z`;

    type SleepBand = { startX: number; endX: number };
    const sleepBands: SleepBand[] = [];
    let bandStart: number | null = null;
    mapped.forEach((p, i) => {
      if (p.isSleep && bandStart === null) bandStart = p.x;
      if (!p.isSleep && bandStart !== null) {
        sleepBands.push({ startX: bandStart, endX: mapped[i - 1]?.x ?? p.x });
        bandStart = null;
      }
    });
    if (bandStart !== null) {
      sleepBands.push({ startX: bandStart, endX: mapped[mapped.length - 1].x });
    }

    const xTicks: number[] = [];
    for (let m = Math.ceil(minMin / 60) * 60; m <= maxMin; m += 120) {
      xTicks.push(m);
    }

    const nowX = toX(nowMinutes);
    const nowInRange = nowMinutes >= minMin && nowMinutes <= maxMin;

    const peakMarkers = events
      .map((ev) => {
        const t = isoToMinutes('started_at' in ev ? ev.started_at : '');
        if (Number.isNaN(t)) return null;
        return toX(t);
      })
      .filter((x): x is number => x !== null && x >= PADDING_LEFT && x <= PADDING_LEFT + chartW);

    const gradId = `lineGrad-${variant}`;
    const areaGradId = `areaGrad-${variant}`;

    return {
      kind: 'ok' as const,
      isStress,
      toMetric,
      toX,
      toY,
      mapped,
      linePath,
      areaPath,
      sleepBands,
      xTicks,
      nowMinutes,
      nowX,
      nowInRange,
      peakMarkers,
      gradId,
      areaGradId,
    };
  }, [points, events, variant, chartH, chartW]);

  if (derived.kind === 'empty') {
    const msg = derived.reason === 'no-data' ? 'No data yet for this day' : 'No waveform data';
    return (
      <View style={[styles.empty, { height }]}>
        <Text style={styles.emptyText}>{msg}</Text>
      </View>
    );
  }

  const {
    isStress,
    toMetric,
    toX,
    toY,
    mapped,
    linePath,
    areaPath,
    sleepBands,
    xTicks,
    nowMinutes,
    nowX,
    nowInRange,
    peakMarkers,
    gradId,
    areaGradId,
  } = derived;

  return (
    <View style={{ width: '100%' }}>
      <Svg
        width="100%"
        height={height}
        viewBox={`0 0 ${SVG_W} ${height}`}
        preserveAspectRatio="none"
      >
        <Defs>
          {/* Line gradient */}
          {isStress && (
            <LinearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0"   stopColor="#34C759" />
              <Stop offset="0.5" stopColor="#F2C94C" />
              <Stop offset="0.8" stopColor="#FF9500" />
              <Stop offset="1"   stopColor="#FF3B30" />
            </LinearGradient>
          )}
          {!isStress && (
            <LinearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0"   stopColor="#FF9500" />
              <Stop offset="0.4" stopColor="#F2C94C" />
              <Stop offset="1"   stopColor="#34C759" />
            </LinearGradient>
          )}
          {/* Area fill gradient */}
          <LinearGradient id={areaGradId} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={isStress ? '#FF9500' : '#34C759'} stopOpacity="0.18" />
            <Stop offset="1" stopColor={isStress ? '#FF9500' : '#34C759'} stopOpacity="0.00" />
          </LinearGradient>
        </Defs>

        {/* Background */}
        <Rect x={0} y={0} width={SVG_W} height={height} fill="#111114" />

        {/* Chart area background */}
        <Rect
          x={PADDING_LEFT}
          y={PADDING_TOP}
          width={chartW}
          height={chartH}
          fill="#0A0A0C"
          rx={4}
        />

        {/* Sleep / rest shading */}
        {sleepBands.map((b, i) => (
          <Rect
            key={i}
            x={b.startX}
            y={PADDING_TOP}
            width={Math.max(1, b.endX - b.startX)}
            height={chartH}
            fill="#FFFFFF"
            opacity={0.06}
          />
        ))}

        {/* Horizontal grid lines at y=1.0, 2.0, 3.0 */}
        {[1, 2, 3].map((v) => {
          const gy = toY(v);
          return (
            <React.Fragment key={v}>
              <Line
                x1={PADDING_LEFT}
                y1={gy}
                x2={PADDING_LEFT + chartW}
                y2={gy}
                stroke="#FFFFFF"
                strokeWidth={0.5}
                opacity={0.1}
              />
              <SvgText
                x={PADDING_LEFT - 6}
                y={gy + 4}
                fill="#555"
                fontSize={9}
                textAnchor="end"
              >
                {v.toFixed(1)}
              </SvgText>
            </React.Fragment>
          );
        })}

        {/* Bottom grid line + 0.0 label */}
        <Line
          x1={PADDING_LEFT}
          y1={PADDING_TOP + chartH}
          x2={PADDING_LEFT + chartW}
          y2={PADDING_TOP + chartH}
          stroke="#FFFFFF"
          strokeWidth={0.5}
          opacity={0.12}
        />
        <SvgText
          x={PADDING_LEFT - 6}
          y={PADDING_TOP + chartH + 4}
          fill="#555"
          fontSize={9}
          textAnchor="end"
        >
          0.0
        </SvgText>

        {/* Event peak markers */}
        {peakMarkers.map((px, i) => (
          <Line
            key={i}
            x1={px}
            y1={PADDING_TOP}
            x2={px}
            y2={PADDING_TOP + chartH}
            stroke={isStress ? Colors.stress : Colors.recovery}
            strokeWidth={1}
            opacity={0.4}
            strokeDasharray="3,3"
          />
        ))}

        {/* Area fill */}
        <Path d={areaPath} fill={`url(#${areaGradId})`} />

        {/* Gradient line */}
        <Path
          d={linePath}
          stroke={`url(#${gradId})`}
          strokeWidth={2}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Personal avg baseline */}
        {personalAvg !== undefined && (() => {
          const avgMetric = toMetric(personalAvg);
          const avgY = toY(avgMetric);
          return (
            <Line
              x1={PADDING_LEFT}
              y1={avgY}
              x2={PADDING_LEFT + chartW}
              y2={avgY}
              stroke={Colors.textMuted}
              strokeWidth={1}
              strokeDasharray="4,4"
              opacity={0.5}
            />
          );
        })()}

        {/* "Now" vertical dashed line */}
        {nowInRange && (
          <>
            <Line
              x1={nowX}
              y1={PADDING_TOP}
              x2={nowX}
              y2={PADDING_TOP + chartH}
              stroke="#FFFFFF"
              strokeWidth={1}
              strokeDasharray="4,3"
              opacity={0.4}
            />
            <Circle
              cx={nowX}
              cy={PADDING_TOP + chartH}
              r={3}
              fill="#FFFFFF"
              opacity={0.6}
            />
          </>
        )}

        {/* X axis labels */}
        {xTicks.map((m) => {
          const lx = toX(m);
          if (lx < PADDING_LEFT || lx > PADDING_LEFT + chartW) return null;
          return (
            <SvgText
              key={m}
              x={lx}
              y={height - 6}
              fill="#555"
              fontSize={9}
              textAnchor="middle"
            >
              {formatHHMM(m)}
            </SvgText>
          );
        })}

        {/* Current time label */}
        {nowInRange && (
          <SvgText
            x={Math.min(nowX + 2, PADDING_LEFT + chartW - 20)}
            y={height - 6}
            fill="#888"
            fontSize={9}
            textAnchor="start"
          >
            {formatHHMM(nowMinutes)}
          </SvgText>
        )}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0A0A0C',
    borderRadius: 8,
  },
  emptyText: {
    color: Colors.textMuted,
    fontSize: 13,
  },
});
