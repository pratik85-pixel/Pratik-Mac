import React, { ReactNode } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  StyleProp,
  ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import Svg, { Circle, Defs, Filter, FeDropShadow } from 'react-native-svg';
import { ZEN } from './theme';

// ─── ZenScreen ────────────────────────────────────────────────────────────────

interface ZenScreenProps {
  children: ReactNode;
  scrollable?: boolean;
  scrollEnabled?: boolean;
  style?: StyleProp<ViewStyle>;
  refreshControl?: React.ReactElement;
}

export function ZenScreen({
  children,
  scrollable = true,
  scrollEnabled = true,
  style,
  refreshControl,
}: ZenScreenProps) {
  const inner = scrollable ? (
    <ScrollView
      contentContainerStyle={[ss.screenScroll, style]}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      scrollEnabled={scrollEnabled}
      refreshControl={refreshControl}
    >
      {children}
    </ScrollView>
  ) : (
    <View style={[ss.screenFlex, style]}>{children}</View>
  );

  return (
    <LinearGradient
      colors={[ZEN.colors.bgTop, ZEN.colors.bgMid, ZEN.colors.bgBottom]}
      locations={[0, 0.42, 1]}
      style={ss.screenGradient}
    >
      <SafeAreaView style={ss.screenSafe} edges={['top', 'bottom']}>
        {inner}
      </SafeAreaView>
    </LinearGradient>
  );
}

// ─── Cards / text primitives ──────────────────────────────────────────────────

interface CardProps {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}

export function SectionCard({ children, style }: CardProps) {
  return (
    <View style={[sc.card, style]}>{children}</View>
  );
}

export function SurfaceCard({ children, style }: CardProps) {
  return (
    <View style={[sv.card, style]}>{children}</View>
  );
}

export function SectionEyebrow({ children }: { children: ReactNode }) {
  return <Text style={ey.text}>{children}</Text>;
}

// ─── ScoreRing ────────────────────────────────────────────────────────────────

interface ScoreRingProps {
  value: string | number | null;
  suffix?: string;
  progress: number;
  color: string;
  size?: number;
  stroke?: number;
}

export function ScoreRing({
  value,
  suffix = '',
  progress,
  color,
  size = 92,
  stroke = 7,
}: ScoreRingProps) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * 0.82;
  const gap  = circumference - dash;
  const offset = dash * (1 - Math.min(1, Math.max(0, progress)));
  const filterId = `glow-${color.replace('#', '')}`;
  const cx = size / 2;
  const cy = size / 2;

  return (
    <View style={{ width: size, height: size }}>
      <Svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: [{ rotate: '-126deg' }] }}
      >
        <Defs>
          <Filter id={filterId} x="-50%" y="-50%" width="200%" height="200%">
            <FeDropShadow
              dx="0"
              dy="0"
              stdDeviation="2"
              floodColor={color}
              floodOpacity="0.28"
            />
          </Filter>
        </Defs>
        <Circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.10)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${gap}`}
        />
        <Circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${gap}`}
          strokeDashoffset={offset}
          filter={`url(#${filterId})`}
        />
      </Svg>
      <View style={[StyleSheet.absoluteFillObject, ring.center]}>
        <Text style={ring.value}>
          {value !== null && value !== undefined ? value : '–'}
          {value !== null && value !== undefined && suffix ? (
            <Text style={ring.suffix}>{suffix}</Text>
          ) : null}
        </Text>
      </View>
    </View>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const ss = StyleSheet.create({
  screenGradient: { flex: 1 },
  screenSafe:     { flex: 1 },
  screenScroll:   { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 32, gap: 16 },
  screenFlex:     { flex: 1, paddingHorizontal: 20, paddingTop: 16 },
});

const sc = StyleSheet.create({
  card: {
    borderRadius:    ZEN.radius.section,
    borderWidth:     1,
    borderColor:     ZEN.colors.border,
    backgroundColor: ZEN.colors.surface,
    padding:         16,
  },
});

const sv = StyleSheet.create({
  card: {
    borderRadius:    ZEN.radius.card,
    borderWidth:     1,
    borderColor:     ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding:         16,
  },
});

const ey = StyleSheet.create({
  text: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2.6,
    color:        ZEN.colors.textMuted,
  },
});

const ring = StyleSheet.create({
  center: {
    alignItems:     'center',
    justifyContent: 'center',
  },
  value: {
    fontSize:      26,
    fontWeight:    '600',
    letterSpacing: -1,
    color:         ZEN.colors.white,
  },
  suffix: {
    fontSize:  12,
    color:     ZEN.colors.textLabel,
  },
});

