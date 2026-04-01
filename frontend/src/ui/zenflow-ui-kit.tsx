/**
 * ZenFlow UI Kit — React Native
 *
 * Faithful translation of the web design system into React Native.
 * All Tailwind values are mapped to exact pixel/point equivalents.
 * Do not introduce new styles here — extend only via the patterns already defined.
 */

import React, { ReactNode, useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import { ArrowLeft } from 'lucide-react-native';
import {
  View,
  Text,
  Modal,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Dimensions,
  useWindowDimensions,
  ViewStyle,
  TextStyle,
  StyleProp,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import Svg, {
  Circle,
  Rect,
  Polyline,
  Polygon,
  Line,
  Path,
  Defs,
  LinearGradient as SvgLinearGradient,
  RadialGradient,
  Stop,
  Filter,
  FeDropShadow,
  Text as SvgText,
  G,
} from 'react-native-svg';

// ─── Constants ────────────────────────────────────────────────────────────────

export { ZEN } from './zen/theme';
import { ZEN } from './zen/theme';
export { ZenScreen, SectionCard, SurfaceCard, SectionEyebrow, ScoreRing } from './zen/primitives';
import { ZenScreen, SectionCard, SurfaceCard, SectionEyebrow, ScoreRing } from './zen/primitives';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ScoreItem {
  label: string;
  value: number;
  suffix?: string;
  progress: number;
  color: string;
  subtext: string;
  onPress?: () => void;
}

export interface InsightItem {
  eyebrow: string;
  title: string;
  body: string;
}

export interface ChartPoint {
  time: string;
  value: number;
  isEvent?: boolean;
  isoTime?: string;
  /** True for waveform points collected during sleep context */
  isSleep?: boolean;
}

export interface StressEvent {
  id?: string;
  time: string;
  label: string;
  contribution: number;
  tagged: boolean;
  tagLabel?: string;
  onTag?: () => void;
}

// ─── ZenHeader ────────────────────────────────────────────────────────────────
// Translates TopHeader

interface ZenHeaderProps {
  eyebrow: string;
  title: string;
  subtitle: string;
  onLeft?: () => void;
  onRight?: () => void;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export function ZenHeader({
  eyebrow,
  title,
  subtitle,
  onLeft,
  onRight,
  leftIcon = '‹',
  rightIcon = '⚙',
}: ZenHeaderProps) {
  return (
    <View style={hdr.wrapper}>
      {/* Top row: left icon | date + greeting | right icon */}
      <View style={hdr.row}>
        <IconButton onPress={onLeft}>{leftIcon}</IconButton>

        <View style={hdr.center}>
          <Text style={hdr.eyebrow}>{eyebrow}</Text>
          <Text style={hdr.subtitle}>{subtitle}</Text>
        </View>

        <IconButton small onPress={onRight}>{rightIcon}</IconButton>
      </View>

      {/* Title row */}
      <View style={hdr.titleRow}>
        <Text style={hdr.overline}>Overview</Text>
        <Text style={hdr.title}>{title}</Text>
      </View>
    </View>
  );
}

// ─── IconButton ───────────────────────────────────────────────────────────────

interface IconButtonProps {
  children: ReactNode;
  small?: boolean;
  onPress?: () => void;
}

export function IconButton({ children, small = false, onPress }: IconButtonProps) {
  return (
    <TouchableOpacity style={ib.btn} activeOpacity={0.8} onPress={onPress}>
      <Text style={small ? ib.textSmall : ib.textLarge}>{children}</Text>
    </TouchableOpacity>
  );
}

// ─── BackBtn ──────────────────────────────────────────────────────────────────
// Standard back button used across all detail screens

export function BackBtn({ onPress }: { onPress: () => void }) {
  return (
    <TouchableOpacity style={bkb.btn} onPress={onPress} activeOpacity={0.8}>
      <ArrowLeft size={18} color={ZEN.colors.textNear} />
    </TouchableOpacity>
  );
}

const bkb = StyleSheet.create({
  btn: {
    width: 40, height: 40, borderRadius: 20,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center', justifyContent: 'center',
  },
});


// ─── BalanceDial helpers (module-level) ────────────────────────────────────────

function _pTC(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function _arc(cx: number, cy: number, r: number, start: number, end: number): string {
  const s = _pTC(cx, cy, r, end);
  const e = _pTC(cx, cy, r, start);
  const laf = end - start <= 180 ? '0' : '1';
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${laf} 0 ${e.x} ${e.y}`;
}

function _valToAngle(v: number): number {
  // -100 → -120°   0 → 0°   +100 → +120°   (240° total sweep)
  const c = Math.min(100, Math.max(-100, v));
  return -120 + ((c + 100) / 200) * 240;
}

function _balanceStatus(v: number): string {
  if (v <= -25) return 'Strained';
  if (v <    0) return 'Stress-leaning';
  if (v <=  25) return 'Balanced';
  return 'Recovery-leaning';
}

// ─── BalanceDial ─────────────────────────────────────────────────────────────
// 240° arc dial — stress gradient left, recovery gradient right.
// Value range: -100 → +100 mapped to -120° → +120°.
// viewBox matches the reference design: 280 × 190, cx=140 cy=120.

interface BalanceDialProps { netBalance: number | null }

export function BalanceDial({ netBalance }: BalanceDialProps) {
  const { width: sw } = useWindowDimensions();
  const dialW = sw - 72;
  const dialH = dialW * (170 / 280);

  const val  = netBalance ?? 0;
  const angle = _valToAngle(val);
  const cx = 140, cy = 108, r = 94, needleLen = 84;
  const TICKS = [-120, -60, 0, 60, 120];
  const leftDot  = _pTC(cx, cy, r, -120);
  const rightDot = _pTC(cx, cy, r,  120);

  const isPos  = val >= 0;
  const color  = isPos ? ZEN.colors.recovery : ZEN.colors.stress;
  const label  = netBalance !== null
    ? (val >= 0 ? `+${Math.round(val)}` : `${Math.round(val)}`) : '–';

  return (
    <View style={{ alignItems: 'center' }}>
      <Svg width={dialW} height={dialH} viewBox="0 0 280 170">
        <Defs>
          {/* Stress arc: fades from transparent to solid blue (left → centre) */}
          <SvgLinearGradient id="dlStress" x1="0%" y1="0%" x2="100%" y2="0%">
            <Stop offset="0%"   stopColor="#1EA7FF" stopOpacity={0.35} />
            <Stop offset="100%" stopColor="#1EA7FF" stopOpacity={0.95} />
          </SvgLinearGradient>
          {/* Recovery arc: solid green → transparent (centre → right) */}
          <SvgLinearGradient id="dlRecovery" x1="0%" y1="0%" x2="100%" y2="0%">
            <Stop offset="0%"   stopColor="#35E27E" stopOpacity={0.95} />
            <Stop offset="100%" stopColor="#35E27E" stopOpacity={0.35} />
          </SvgLinearGradient>
          {/* Hub radial glow */}
          <RadialGradient id="dlHub" cx="50%" cy="50%" r="50%">
            <Stop offset="0%"   stopColor="#ffffff" stopOpacity={0.75} />
            <Stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
          </RadialGradient>

        </Defs>

        {/* Stress arc: -120° → 0° */}
        <Path d={_arc(cx, cy, r, -120, 0)}
          stroke="url(#dlStress)" strokeWidth={18} fill="none" strokeLinecap="round" />

        {/* Recovery arc: 0° → +120° */}
        <Path d={_arc(cx, cy, r, 0, 120)}
          stroke="url(#dlRecovery)" strokeWidth={18} fill="none" strokeLinecap="round" />

        {/* Thin guide ring over the full 240° span */}
        <Path d={_arc(cx, cy, r, -120, 120)}
          stroke="rgba(255,255,255,0.08)" strokeWidth={2} fill="none" strokeLinecap="round" />

        {/* Tick marks at each 60° step */}
        {TICKS.map((t) => {
          const outer = _pTC(cx, cy, 112, t);
          const inner = _pTC(cx, cy, 101, t);
          return (
            <Line key={t}
              x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
              stroke="rgba(255,255,255,0.22)" strokeWidth={2} strokeLinecap="round" />
          );
        })}

        {/* Needle — rotates around cx,cy */}
        <G transform={`rotate(${angle}, ${cx}, ${cy})`}>
          <Line x1={cx} y1={cy} x2={cx} y2={cy - needleLen}
            stroke="#7CFFAF" strokeWidth={5} strokeLinecap="round" />
          <Circle cx={cx} cy={cy - needleLen} r={5} fill="#7CFFAF" />
        </G>

        {/* Hub circles */}
        <Circle cx={cx} cy={cy} r={18} fill="url(#dlHub)" opacity={0.55} />
        <Circle cx={cx} cy={cy} r={10} fill="#D8E1F0" opacity={0.16} />
        <Circle cx={cx} cy={cy} r={5}  fill="#B9C7DA" />

        {/* Arc-end anchor dots */}
        <Circle cx={leftDot.x}  cy={leftDot.y}  r={5} fill="#1EA7FF" opacity={0.7} />
        <Circle cx={rightDot.x} cy={rightDot.y} r={5} fill="#35E27E" opacity={0.7} />
      </Svg>

      {/* Net balance number */}
      <Text style={{ fontSize: 56, fontWeight: '600', color, letterSpacing: -2, lineHeight: 62, marginTop: -6 }}>
        {label}
      </Text>
      {/* Status descriptor */}
      <Text style={{ fontSize: 18, fontWeight: '500', color, marginTop: 2, letterSpacing: -0.2 }}>
        {netBalance !== null ? _balanceStatus(val) : 'Gathering data…'}
      </Text>
    </View>
  );
}

// ─── ScoreTile ────────────────────────────────────────────────────────────────

export function ScoreTile({ label, value, suffix = '', progress, color, subtext, onPress }: ScoreItem) {
  return (
    <TouchableOpacity
      style={st.tile}
      activeOpacity={0.75}
      onPress={onPress}
      disabled={!onPress}
    >
      <View style={st.ringWrap}>
        <ScoreRing value={value} suffix={suffix} progress={progress} color={color} />
      </View>
      <View style={st.meta}>
        <Text style={st.label} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{label}</Text>
        <Text style={st.sub} numberOfLines={1}>{subtext}</Text>
      </View>
    </TouchableOpacity>
  );
}

// ─── CoachSummary ─────────────────────────────────────────────────────────────

interface CoachSummaryProps {
  title: string;
  body: string;
}

export function CoachSummary({ title, body }: CoachSummaryProps) {
  return (
    <SurfaceCard style={cs.card}>
      <SectionEyebrow>{title}</SectionEyebrow>
      <Text style={cs.body}>{body}</Text>
    </SurfaceCard>
  );
}

// ─── ZenPrimaryButton ────────────────────────────────────────────────────────
// Named with Zen prefix to avoid collision with existing RN Button

interface ZenPrimaryButtonProps {
  eyebrow: string;
  label: string;
  rightIcon?: string;
  onPress?: () => void;
}

export function ZenPrimaryButton({
  eyebrow,
  label,
  rightIcon = '→',
  onPress,
}: ZenPrimaryButtonProps) {
  return (
    <TouchableOpacity style={pb.btn} activeOpacity={0.8} onPress={onPress}>
      <View>
        <Text style={pb.eyebrow}>{eyebrow}</Text>
        <Text style={pb.label}>{label}</Text>
      </View>
      <Text style={pb.arrow}>{rightIcon}</Text>
    </TouchableOpacity>
  );
}

// ─── InfoCard ─────────────────────────────────────────────────────────────────

export function InfoCard({ eyebrow, title, body }: InsightItem) {
  return (
    <View style={ic.card}>
      <Text style={ic.eyebrow}>{eyebrow}</Text>
      <Text style={ic.title}>{title}</Text>
      <Text style={ic.body}>{body}</Text>
    </View>
  );
}

// ─── StressChartCard ─────────────────────────────────────────────────────────
// Premium SVG line + area chart — smooth bezier curves, subtle glow

interface StressChartCardProps {
  data: ChartPoint[];
  windowLabel?: string;
  /** Index of the highlighted point (defaults to roughly 2/3 through) */
  highlightIndex?: number;
}

/** Midpoint cubic-bezier smooth path. Input: [x, y] tuple array. */
function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return '';
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[i + 1];
    const cx = (x1 + x2) / 2;
    d += ` C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
  }
  return d;
}

/** Format "9:05 AM" → "9a", "2:30 PM" → "2p" */
function fmtHour(timeStr: string): string {
  const m = timeStr.match(/^(\d+):\d+\s*(AM|PM)$/i);
  if (!m) return timeStr;
  return m[1] + (m[2].toUpperCase() === 'AM' ? 'a' : 'p');
}

/** Parse "9:05 AM" → fractional hour 0–24 */
function timeToHour(timeStr: string): number {
  const m = timeStr.match(/^(\d+):(\d+)\s*(AM|PM)$/i);
  if (!m) return 0;
  let h = parseInt(m[1]);
  const min = parseInt(m[2]);
  const pm  = m[3].toUpperCase() === 'PM';
  if (pm && h !== 12) h += 12;
  if (!pm && h === 12) h = 0;
  return h + min / 60;
}

/** Reduce array to at most maxPts evenly spaced samples */
function downsample<T>(arr: T[], maxPts: number): T[] {
  if (arr.length <= maxPts) return arr;
  return Array.from({ length: maxPts }, (_, i) =>
    arr[Math.round(i * (arr.length - 1) / (maxPts - 1))]
  );
}

// Fixed x-axis tick labels: midnight → 6a → noon → 6p → midnight
const DAY_TICKS: { hour: number; label: string }[] = [
  { hour: 0,  label: '00' },
  { hour: 6,  label: '06' },
  { hour: 12, label: '12' },
  { hour: 18, label: '18' },
  { hour: 24, label: '24' },
];

/** Build data-driven x-axis anchor labels from actual chart data isoTimes. */
function buildXLabels(data: ChartPoint[], totalWidth: number): { label: string; x: number }[] {
  const pts = data.filter(p => p.isoTime);
  if (pts.length < 2) return [];
  const BAR_W = 5, BAR_GAP = 1.5, BAR_SLOT = BAR_W + BAR_GAP;
  // Pick 5 evenly-spaced indices across the data
  const indices = [0, 0.25, 0.5, 0.75, 1].map(f => Math.round(f * (data.length - 1)));
  const unique = [...new Set(indices)];
  return unique.map(idx => {
    const iso = data[idx].isoTime!;
    const d = new Date(iso);
    const h = d.getHours(), m = d.getMinutes();
    const suffix = h < 12 ? 'am' : 'pm';
    const hh = h % 12 === 0 ? 12 : h % 12;
    const label = m === 0 ? `${hh}${suffix}` : `${hh}:${String(m).padStart(2,'0')}${suffix}`;
    return { label, x: Math.round(idx * BAR_SLOT) };
  });
}

/** Round rawMax up to a clean chart ceiling: 1 → 2 → 5 → 10 → … × 10^n */
function niceMax(rawMax: number): number {
  if (rawMax <= 0) return 0.1;
  const mag = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const n   = rawMax / mag;
  const ceil = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return parseFloat((ceil * mag).toPrecision(6));
}

/** Y-axis tick label: 1 dp if < 1, integer otherwise */
function fmtTick(v: number): string {
  if (v === 0) return '0';
  return v < 1 ? v.toFixed(1) : String(Math.round(v));
}

export function StressChartCard({ data }: { data: ChartPoint[] }) {
  const BAR_W = 5;
  const BAR_GAP = 1.5;
  const BAR_MAX_H = 160;
  const scrollRef = React.useRef<any>(null);

  React.useEffect(() => {
    setTimeout(() => scrollRef.current?.scrollToEnd?.({ animated: false }), 150);
  }, [data.length]);

  if (!data || data.length === 0) {
    return <SurfaceCard style={ch.card}><Text style={ch.empty}>No data yet</Text></SurfaceCard>;
  }

  const rawMax = data.reduce((m, p) => Math.max(m, p.value), 0);
  const yMax   = niceMax(rawMax);
  const yTicks = [yMax, parseFloat((yMax / 2).toPrecision(4)), 0];

  return (
    <SurfaceCard style={ch.card}>
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: 26, height: BAR_MAX_H, position: 'relative', marginRight: 4 }}>
          {yTicks.map(v => (
            <Text
              key={v}
              style={[ch.yLabel, { position: 'absolute', top: Math.round((1 - v / yMax) * BAR_MAX_H) - 5 }]}
            >{fmtTick(v)}</Text>
          ))}
          <Text style={[ch.yUnit, { position: 'absolute', bottom: -14 }]}>ms</Text>
        </View>
        <ScrollView
          ref={scrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingHorizontal: 4, paddingBottom: 0 }}
        >
          {(() => {
            const BAR_SLOT = BAR_W + BAR_GAP;
            const totalWidth = data.length * BAR_SLOT;
            const xLabels = buildXLabels(data, totalWidth);
            return (
              <View>
                <View style={{ flexDirection: 'row', alignItems: 'flex-end', height: BAR_MAX_H }}>
                  {data.map((pt, i) => (
                    <View
                      key={i}
                      style={{
                        width: BAR_W,
                        marginRight: BAR_GAP,
                        height: Math.max(2, Math.round((Math.min(pt.value, yMax) / yMax) * BAR_MAX_H)),
                        backgroundColor: pt.isSleep
                          ? 'rgba(242,209,76,0.40)'
                          : pt.isEvent
                          ? ZEN.colors.stress
                          : 'rgba(25, 181, 254, 0.28)',
                        borderRadius: 2,
                      }}
                    />
                  ))}
                </View>
                <View style={{ height: 14, position: 'relative', width: totalWidth }}>
                  {xLabels.map((t, i) => (
                    <Text key={i} style={[ch.xLabel, { position: 'absolute', left: Math.max(0, t.x - 18) }]}>{t.label}</Text>
                  ))}
                </View>
              </View>
            );
          })()} 
        </ScrollView>
      </View>
      <View style={ch.legend}>
        <View style={[ch.legendDot, { backgroundColor: ZEN.colors.stress }]} />
        <Text style={ch.legendText}>Stress event</Text>
        <View style={[ch.legendDot, { backgroundColor: 'rgba(25,181,254,0.28)', marginLeft: 12 }]} />
        <Text style={ch.legendText}>Regular activity</Text>
      </View>
    </SurfaceCard>
  );
}

// ─── StressEventRow ───────────────────────────────────────────────────────────

export function StressEventRow({ event }: { event: StressEvent }) {
  return (
    <SurfaceCard style={er.card}>
      <View style={er.row}>
        <View style={er.left}>
          <Text style={er.time}>{event.time}</Text>
          {event.tagged ? (
            <View style={er.taggedRow}>
              <Text style={er.taggedCheck}>✓</Text>
              <Text style={[er.label, { color: ZEN.colors.recovery }]}>
                {event.tagLabel ?? 'Tagged'}
              </Text>
            </View>
          ) : (
            <Text style={er.label}>Stress Event</Text>
          )}
        </View>
        {!event.tagged && (
          <TouchableOpacity style={er.tagCta} activeOpacity={0.75} onPress={event.onTag}>
            <Text style={er.tagCtaText}>Tap to tag</Text>
          </TouchableOpacity>
        )}
      </View>
    </SurfaceCard>
  );
}

// ─── TagBottomSheet ───────────────────────────────────────────────────────────

interface TagBottomSheetProps {
  visible?: boolean;
  options: string[];
  eventLabel?: string;
  eventTime?: string;
  onSelect?: (tag: string) => void;
  onSkip?: () => void;
}

export function TagBottomSheet({
  visible = false,
  options,
  eventLabel = '',
  eventTime = '',
  onSelect,
  onSkip,
}: TagBottomSheetProps) {
  const [customMode, setCustomMode] = useState(false);
  const [customText, setCustomText] = useState('');

  const handleClose = () => {
    setCustomMode(false);
    setCustomText('');
    onSkip?.();
  };

  const handleSelect = (tag: string) => {
    setCustomMode(false);
    setCustomText('');
    onSelect?.(tag);
  };

  const handleCustomConfirm = () => {
    const trimmed = customText.trim();
    if (!trimmed) return;
    handleSelect(trimmed);
  };

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={handleClose}>
      <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.55)' }}>
        <TouchableOpacity style={StyleSheet.absoluteFillObject} activeOpacity={1} onPress={handleClose} />
        <View style={tbs.sheet}>
          <View style={tbs.handle} />
          <View style={tbs.header}>
            <View>
              <SectionEyebrow>Tag this event</SectionEyebrow>
              <Text style={tbs.eventText}>
                {eventLabel}{eventTime ? ` · ${eventTime}` : ''}
              </Text>
            </View>
            <TouchableOpacity onPress={handleClose} activeOpacity={0.75}>
              <Text style={tbs.skip}>Skip</Text>
            </TouchableOpacity>
          </View>

          {customMode ? (
            <View style={tbs.customRow}>
              <TextInput
                style={tbs.customInput}
                value={customText}
                onChangeText={setCustomText}
                placeholder="Describe the event…"
                placeholderTextColor={ZEN.colors.textMuted}
                autoFocus
                returnKeyType="done"
                onSubmitEditing={handleCustomConfirm}
              />
              <TouchableOpacity
                style={[tbs.optBtn, { minWidth: 0, flex: 0, paddingHorizontal: 16 }]}
                activeOpacity={0.75}
                onPress={handleCustomConfirm}
              >
                <Text style={tbs.optText}>Save</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={tbs.grid}>
              {options.map(opt => (
                <TouchableOpacity
                  key={opt}
                  style={tbs.optBtn}
                  activeOpacity={0.75}
                  onPress={() => handleSelect(opt)}
                >
                  <Text style={tbs.optText}>{opt}</Text>
                </TouchableOpacity>
              ))}
              <TouchableOpacity
                style={[tbs.optBtn, { borderColor: ZEN.colors.borderStrong }]}
                activeOpacity={0.75}
                onPress={() => setCustomMode(true)}
              >
                <Text style={[tbs.optText, { color: ZEN.colors.textSecondary }]}>Custom…</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// StyleSheets
// ═══════════════════════════════════════════════════════════════════════════════

const hdr = StyleSheet.create({
  wrapper:  { marginBottom: 8 },
  row: {
    flexDirection:  'row',
    alignItems:     'center',
    justifyContent: 'space-between',
    marginBottom:   20,
  },
  center: { alignItems: 'center' },
  eyebrow: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 3.5,
    color:        ZEN.colors.textHalf,
  },
  subtitle: {
    marginTop:   4,
    fontSize:    14,
    fontWeight:  '500',
    color:       ZEN.colors.textNear,
  },
  titleRow: { marginBottom: 16 },
  overline: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2.6,
    color:        ZEN.colors.textMuted,
  },
  title: {
    marginTop:    8,
    fontSize:     34,
    fontWeight:   '600',
    letterSpacing: -1,
    color:        ZEN.colors.white,
  },
});

const ib = StyleSheet.create({
  btn: {
    width:           40,
    height:          40,
    borderRadius:    20,
    borderWidth:     1,
    borderColor:     'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems:      'center',
    justifyContent:  'center',
  },
  textLarge: { fontSize: 18, color: ZEN.colors.textNear },
  textSmall: { fontSize: 14, color: ZEN.colors.textNear },
});

const st = StyleSheet.create({
  tile: {
    flex:            1,
    borderRadius:    ZEN.radius.card,
    borderWidth:     1,
    borderColor:     ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding:         12,
    alignItems:      'center',
  },
  ringWrap: { alignItems: 'center' },
  meta:     { marginTop: 12, alignItems: 'center' },
  label: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    color:        ZEN.colors.textLabel,
  },
  sub: {
    marginTop: 4,
    fontSize:  11,
    color:    ZEN.colors.textMuted,
    textAlign: 'center',
  },
});

const cs = StyleSheet.create({
  card: { marginTop: 20 },
  body: {
    marginTop:  12,
    fontSize:   16,
    lineHeight: 28,
    color:     ZEN.colors.textBody,
  },
});

const pb = StyleSheet.create({
  btn: {
    marginTop:       16,
    height:          56,
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'space-between',
    borderRadius:    ZEN.radius.button,
    borderWidth:     1,
    borderColor:     ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surfaceStrong,
    paddingHorizontal: 20,
  },
  eyebrow: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2.6,
    color:        ZEN.colors.textMuted,
  },
  label: {
    marginTop:  4,
    fontSize:   16,
    fontWeight: '500',
    color:     ZEN.colors.textAlmost,
  },
  arrow: {
    fontSize: 20,
    color:   ZEN.colors.textSoft,
  },
});

const ic = StyleSheet.create({
  card: {
    borderRadius:    ZEN.radius.card,
    borderWidth:     1,
    borderColor:     ZEN.colors.border,
    backgroundColor: ZEN.colors.surface,
    padding:         16,
  },
  eyebrow: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2.6,
    color:        ZEN.colors.textMuted,
  },
  title: {
    marginTop:     8,
    fontSize:      18,
    fontWeight:    '500',
    letterSpacing: -0.36,
    color:        ZEN.colors.textPrimary,
  },
  body: {
    marginTop:  8,
    fontSize:   14,
    lineHeight: 24,
    color:     ZEN.colors.textSecondary,
  },
});

const ch = StyleSheet.create({
  card:       { padding: 16 },
  empty:      { color: ZEN.colors.textMuted, fontSize: 13, textAlign: 'center', paddingVertical: 40 },
  legend:     { flexDirection: 'row', alignItems: 'center', marginTop: 10, gap: 4 },
  legendDot:  { width: 8, height: 8, borderRadius: 4 },
  legendText: { fontSize: 11, color: ZEN.colors.textMuted },
  yLabel:     { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'right', width: 24 },
  yUnit:      { fontSize: 7, color: ZEN.colors.textMuted, textAlign: 'right', width: 24, marginTop: 2, textTransform: 'uppercase', letterSpacing: 0.5 },
  xLabel:     { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'center', width: 36 },
});

const er = StyleSheet.create({
  card: { padding: 16, marginBottom: 0 },
  row: {
    flexDirection:  'row',
    alignItems:     'flex-start',
    justifyContent: 'space-between',
    gap:            16,
  },
  left:    { flex: 1 },
  topRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:           8,
    marginBottom:  8,
  },
  time: {
    fontSize:      12,
    textTransform: 'uppercase',
    letterSpacing: 1.8,
    color:        ZEN.colors.textQuiet,
  },
  tagPill: {
    borderRadius:    ZEN.radius.pill,
    borderWidth:     1,
    borderColor:     ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  tagPillText: {
    fontSize:      10,
    textTransform: 'uppercase',
    letterSpacing: 1.6,
    color:        ZEN.colors.textFaint,
  },
  tagCta: {
    borderRadius:    ZEN.radius.pill,
    borderWidth:     1,
    borderColor:     ZEN.colors.stressTagBorder,
    backgroundColor: ZEN.colors.stressTagBg,
    paddingHorizontal: 14,
    paddingVertical:   8,
  },
  tagCtaText: {
    fontSize:   12,
    fontWeight: '600',
    color:      ZEN.colors.stressTagText,
  },
  label: {
    fontSize:      17,
    fontWeight:    '500',
    letterSpacing: -0.34,
    color:        ZEN.colors.textAlmost,
  },
  taggedRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:            6,
    marginTop:      2,
  },
  taggedCheck: {
    fontSize:   16,
    color:      ZEN.colors.recovery,
    fontWeight: '700',
  },
  desc: {
    marginTop: 8,
    fontSize:  13,
    lineHeight: 20,
    color:    ZEN.colors.textSubtle,
  },
  right:   { alignItems: 'flex-end' },
  contribLabel: {
    fontSize:      10,
    textTransform: 'uppercase',
    letterSpacing: 1.8,
    color:        ZEN.colors.textDim,
  },
  contribValue: {
    marginTop:    8,
    fontSize:     24,
    fontWeight:   '600',
    letterSpacing: -0.7,
    color:        ZEN.colors.white,
  },
});

const tbs = StyleSheet.create({
  sheet: {
    borderRadius:    ZEN.radius.section,
    borderWidth:     1,
    borderColor:     ZEN.colors.borderStrong,
    backgroundColor: 'rgba(15, 18, 34, 0.98)',
    paddingHorizontal: 16,
    paddingBottom:   32,
    paddingTop:      12,
  },
  handle: {
    alignSelf:       'center',
    width:           56,
    height:          6,
    borderRadius:    ZEN.radius.pill,
    backgroundColor: ZEN.colors.dragHandle,
    marginBottom:    16,
  },
  header: {
    flexDirection:  'row',
    alignItems:     'flex-start',
    justifyContent: 'space-between',
    gap:            16,
    marginBottom:   16,
  },
  eventText: {
    marginTop: 4,
    fontSize:  15,
    color:    ZEN.colors.textWarm,
  },
  skip: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2,
    color:        ZEN.colors.textQuiet,
    paddingTop:    4,
  },
  grid: {
    flexDirection:  'row',
    flexWrap:       'wrap',
    gap:            8,
  },
  optBtn: {
    flex:            1,
    minWidth:        '45%',
    borderRadius:    ZEN.radius.tab,
    borderWidth:     1,
    borderColor:     ZEN.colors.border,
    backgroundColor: ZEN.colors.surface,
    paddingHorizontal: 12,
    paddingVertical:   12,
  },
  optText: {
    fontSize:   13,
    fontWeight: '500',
    color:     ZEN.colors.textBody,
  },
  customRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:           8,
    marginBottom:  8,
  },
  customInput: {
    flex:            1,
    borderRadius:    ZEN.radius.tab,
    borderWidth:     1,
    borderColor:     ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    paddingHorizontal: 12,
    paddingVertical:   12,
    fontSize:        13,
    color:           ZEN.colors.textBody,
  },
});

// ════════════════════════════════════════════════════════════════════════════
// II. Recovery detail components
// ════════════════════════════════════════════════════════════════════════════

export interface RecoveryEvent {
  id?: string;
  time: string;
  label: string;
  contribution: number;
  tagged: boolean;
  tagLabel?: string;
  onTag?: () => void;
}

// ─── RecoveryChartCard ───────────────────────────────────────────────────────

export function RecoveryChartCard({
  data,
  legend = { recoveryWindow: true, regularActivity: true, sleep: true },
}: {
  data: ChartPoint[];
  legend?: { recoveryWindow?: boolean; regularActivity?: boolean; sleep?: boolean };
}) {
  const BAR_W = 5;
  const BAR_GAP = 1.5;
  const BAR_MAX_H = 160;
  const scrollRef = React.useRef<any>(null);

  React.useEffect(() => {
    setTimeout(() => scrollRef.current?.scrollToEnd?.({ animated: false }), 150);
  }, [data.length]);

  if (!data || data.length === 0) {
    return <SurfaceCard style={ch2.card}><Text style={ch2.empty}>No recovery data yet</Text></SurfaceCard>;
  }

  const rawMax = data.reduce((m, p) => Math.max(m, p.value), 0);
  const yMax   = niceMax(rawMax);
  const yTicks = [yMax, parseFloat((yMax / 2).toPrecision(4)), 0];

  return (
    <SurfaceCard style={ch2.card}>
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: 26, height: BAR_MAX_H, position: 'relative', marginRight: 4 }}>
          {yTicks.map(v => (
            <Text
              key={v}
              style={[ch2.yLabel, { position: 'absolute', top: Math.round((1 - v / yMax) * BAR_MAX_H) - 5 }]}
            >{fmtTick(v)}</Text>
          ))}
          <Text style={[ch2.yUnit, { position: 'absolute', bottom: -14 }]}>ms</Text>
        </View>
        <ScrollView
          ref={scrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingHorizontal: 4, paddingBottom: 0 }}
        >
          {(() => {
            const BAR_SLOT = BAR_W + BAR_GAP;
            const totalWidth = data.length * BAR_SLOT;
            const xLabels = buildXLabels(data, totalWidth);
            return (
              <View>
                <View style={{ flexDirection: 'row', alignItems: 'flex-end', height: BAR_MAX_H }}>
                  {data.map((pt, i) => (
                    <View
                      key={i}
                      style={{
                        width: BAR_W,
                        marginRight: BAR_GAP,
                        height: Math.max(2, Math.round((Math.min(pt.value, yMax) / yMax) * BAR_MAX_H)),
                        backgroundColor: pt.isSleep
                          ? 'rgba(242,209,76,0.40)'
                          : pt.isEvent
                          ? ZEN.colors.recovery
                          : 'rgba(57, 226, 125, 0.28)',
                        borderRadius: 2,
                      }}
                    />
                  ))}
                </View>
                <View style={{ height: 14, position: 'relative', width: totalWidth }}>
                  {xLabels.map((t, i) => (
                    <Text key={i} style={[ch2.xLabel, { position: 'absolute', left: Math.max(0, t.x - 18) }]}>{t.label}</Text>
                  ))}
                </View>
              </View>
            );
          })()} 
        </ScrollView>
      </View>
      <View style={ch2.legend}>
        {legend.recoveryWindow ? (
          <>
            <View style={[ch2.legendDot, { backgroundColor: ZEN.colors.recovery }]} />
            <Text style={ch2.legendText}>Recovery window</Text>
          </>
        ) : null}
        {legend.regularActivity ? (
          <>
            <View style={[ch2.legendDot, { backgroundColor: 'rgba(57,226,125,0.45)', marginLeft: 12 }]} />
            <Text style={ch2.legendText}>Regular activity</Text>
          </>
        ) : null}
        {legend.sleep ? (
          <>
            <View style={[ch2.legendDot, { backgroundColor: 'rgba(242,209,76,0.40)', marginLeft: 12 }]} />
            <Text style={ch2.legendText}>Sleep</Text>
          </>
        ) : null}
      </View>
    </SurfaceCard>
  );
}

// ─── RecoveryEventRow ────────────────────────────────────────────────────────

export function RecoveryEventRow({ event }: { event: RecoveryEvent }) {
  return (
    <SurfaceCard style={re.card}>
      <View style={re.row}>
        <View style={re.left}>
          <Text style={re.time}>{event.time}</Text>
          {event.tagged ? (
            <View style={re.taggedRow}>
              <Text style={re.taggedCheck}>✓</Text>
              <Text style={[re.label, { color: ZEN.colors.recovery }]}>
                {event.tagLabel ?? 'Tagged'}
              </Text>
            </View>
          ) : (
            <Text style={re.label}>Recovery Window</Text>
          )}
        </View>
        {!event.tagged && (
          <TouchableOpacity style={re.tagCta} activeOpacity={0.75} onPress={event.onTag}>
            <Text style={re.tagCtaText}>Tap to tag</Text>
          </TouchableOpacity>
        )}
      </View>
    </SurfaceCard>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// III. Readiness components
// ════════════════════════════════════════════════════════════════════════════

interface BreakdownRowProps {
  label: string;
  value: string;
  note: string;
  highlight?: boolean;
}

export function BreakdownRow({ label, value, note, highlight = false }: BreakdownRowProps) {
  return (
    <View style={[br.row, highlight && br.rowHighlight]}>
      <View style={br.left}>
        <Text style={br.label}>{label}</Text>
        <Text style={br.note}>{note}</Text>
      </View>
      <Text style={[br.value, highlight && br.valueHighlight]}>{value}</Text>
    </View>
  );
}

// ─── CombinedBalanceChart ────────────────────────────────────────────────────
// WHOOP-style dual-line chart: stress (blue) + recovery (green) over N days.
// Props-driven, real-time ready.

export interface BalanceDayPoint {
  label: string;       // e.g. "Sat 14"
  stress: number | null;
  recovery: number | null;
}

interface CombinedBalanceChartProps {
  data: BalanceDayPoint[];
  title?: string;
  stressDisplayScale?: '0-100' | '0-10';
}

export function CombinedBalanceChart({
  data,
  title = 'Strain & Recovery',
  stressDisplayScale = '0-100',
}: CombinedBalanceChartProps) {
  const { width: screenWidth } = Dimensions.get('window');
  const W  = screenWidth - 40 - 24;
  const H  = 176;
  const pX = 12, pTop = 14, pBottom = 10;
  const iW = W - pX * 2;
  const iH = H - pTop - pBottom;

  const validData = data.filter(d => d.stress !== null || d.recovery !== null);

  if (validData.length < 2) {
    return (
      <SurfaceCard style={cbc.card}>
        <SectionEyebrow>{title}</SectionEyebrow>
        <View style={cbc.empty}>
          <Text style={cbc.emptyText}>Building your 7-day trend…</Text>
          <Text style={cbc.emptyHint}>Appears after a few days of data</Text>
        </View>
      </SurfaceCard>
    );
  }

  const n = validData.length;
  const xFor = (i: number) => pX + (i / (n - 1)) * iW;
  const yFor = (v: number)  => pTop + (1 - Math.min(1, Math.max(0, v / 100))) * iH;

  const stressPts: [number, number][]   = validData
    .map((d, i): [number, number] | null =>
      d.stress !== null ? [xFor(i), yFor(d.stress)] : null)
    .filter((p): p is [number, number] => p !== null);

  const recovPts: [number, number][]  = validData
    .map((d, i): [number, number] | null =>
      d.recovery !== null ? [xFor(i), yFor(d.recovery)] : null)
    .filter((p): p is [number, number] => p !== null);

  const stressLine   = stressPts.length > 1  ? smoothPath(stressPts)  : '';
  const recoveryLine = recovPts.length  > 1  ? smoothPath(recovPts)   : '';

  return (
    <SurfaceCard style={cbc.card}>
      <View style={cbc.header}>
        <SectionEyebrow>{title}</SectionEyebrow>
        <View style={cbc.legend}>
          <View style={cbc.legendItem}>
            <View style={[cbc.legendDot, { backgroundColor: ZEN.colors.stress }]} />
            <Text style={cbc.legendLabel}>
              {stressDisplayScale === '0-10' ? 'Stress (0-10)' : 'Stress'}
            </Text>
          </View>
          <View style={cbc.legendItem}>
            <View style={[cbc.legendDot, { backgroundColor: ZEN.colors.recovery }]} />
            <Text style={cbc.legendLabel}>Recovery</Text>
          </View>
        </View>
      </View>

      <Svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map(r => (
          <Line key={r}
            x1={pX} x2={W - pX}
            y1={pTop + iH * r} y2={pTop + iH * r}
            stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
        ))}

        {/* Recovery line */}
        {recoveryLine ? (
          <Path d={recoveryLine} fill="none" stroke={ZEN.colors.recovery}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        ) : null}

        {/* Stress line */}
        {stressLine ? (
          <Path d={stressLine} fill="none" stroke={ZEN.colors.stress}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        ) : null}

        {/* Recovery dots + value labels (below) */}
        {validData.map((d, i) => {
          if (d.recovery === null) return null;
          const x = xFor(i), y = yFor(d.recovery);
          return (
            <G key={`r${i}`}>
              <Circle cx={x} cy={y} r="4.5" fill={ZEN.colors.recovery} />
              <SvgText x={x} y={y + 16} fontSize="9" fontWeight="600"
                fill={ZEN.colors.recovery} textAnchor="middle">
                {Math.round(d.recovery)}
              </SvgText>
            </G>
          );
        })}

        {/* Stress dots + value labels (above) */}
        {validData.map((d, i) => {
          if (d.stress === null) return null;
          const x = xFor(i), y = yFor(d.stress);
          return (
            <G key={`s${i}`}>
              <Circle cx={x} cy={y} r="4.5" fill={ZEN.colors.stress} />
              <SvgText x={x} y={y - 8} fontSize="9" fontWeight="600"
                fill={ZEN.colors.stress} textAnchor="middle">
                {stressDisplayScale === '0-10'
                  ? (Math.round((d.stress / 10) * 10) / 10).toFixed(1)
                  : Math.round(d.stress)}
              </SvgText>
            </G>
          );
        })}

      </Svg>
      {/* X-axis day labels — native Text to avoid SVG vertical-rendering bug */}
      <View style={{ height: 16, position: 'relative', width: W, marginTop: 2 }}>
        {validData.map((d, i) => (
          <Text
            key={`x${i}`}
            style={[cbc.xLabel, { position: 'absolute', left: Math.max(0, Math.round(xFor(i)) - 18) }]}
          >
            {d.label}
          </Text>
        ))}
      </View>
    </SurfaceCard>
  );
}

// ─── DivergingWindowChart ────────────────────────────────────────────────────

export interface DivergingWindowPoint {
  window_start: string;
  window_end:   string;
  rmssd_ms:     number | null;
  hr_bpm:       number | null;
  context:      string;
  is_valid:     boolean;
}

interface DivergingWindowChartProps {
  windows:    DivergingWindowPoint[];
  morningAvg: number;
  title?:     string;
}

export function DivergingWindowChart({
  windows,
  morningAvg,
  title = "Today's windows",
}: DivergingWindowChartProps) {
  const BAR_W    = 5;
  const BAR_GAP  = 2;
  const HALF_H   = 70; // px above / below the centre line
  const NUB_THRESHOLD = 1; // ms delta treated as baseline

  const valid = windows.filter(
    w => w.is_valid && w.context === 'background' && w.rmssd_ms !== null,
  );

  if (valid.length === 0) {
    return (
      <SurfaceCard style={dwc.card}>
        <SectionEyebrow>{title}</SectionEyebrow>
        <Text style={dwc.empty}>No waking windows yet today</Text>
      </SurfaceCard>
    );
  }

  // Scale: find max absolute delta so bars fill the half-height
  const maxDelta = valid.reduce((m, w) => Math.max(m, Math.abs((w.rmssd_ms as number) - morningAvg)), 0);
  const scale    = maxDelta > 0 ? HALF_H / maxDelta : 1;

  function fmtTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  }

  // Show x-axis labels every ~6 windows to avoid crowding
  const labelStep = Math.max(1, Math.floor(valid.length / 6));

  return (
    <SurfaceCard style={dwc.card}>
      <SectionEyebrow>{title}</SectionEyebrow>

      {/* Legend */}
      <View style={dwc.legend}>
        <View style={dwc.legendItem}>
          <View style={[dwc.legendDot, { backgroundColor: ZEN.colors.recovery }]} />
          <Text style={dwc.legendText}>Recovery</Text>
        </View>
        <View style={dwc.legendItem}>
          <View style={[dwc.legendDot, { backgroundColor: ZEN.colors.stress }]} />
          <Text style={dwc.legendText}>Stress</Text>
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={{ marginTop: 8 }}
        contentContainerStyle={{ paddingHorizontal: 4 }}
      >
        <View>
          {/* Chart area: HALF_H above + 1px line + HALF_H below */}
          <View style={{ height: HALF_H * 2 + 1, flexDirection: 'row', alignItems: 'center' }}>
            {/* Grid lines */}
            <View style={[dwc.gridLine, { top: 0 }]} />
            <View style={[dwc.gridLine, { top: Math.round(HALF_H / 2) }]} />
            <View style={[dwc.gridLine, { top: HALF_H, borderColor: 'rgba(255,255,255,0.25)' }]} />
            <View style={[dwc.gridLine, { top: HALF_H + Math.round(HALF_H / 2) }]} />
            <View style={[dwc.gridLine, { top: HALF_H * 2 }]} />

            {/* Bars */}
            <View style={{ flexDirection: 'row', alignItems: 'center', height: HALF_H * 2 + 1 }}>
              {valid.map((w, i) => {
                const delta     = (w.rmssd_ms as number) - morningAvg;
                const isNub     = Math.abs(delta) < NUB_THRESHOLD;
                const barH      = isNub ? 2 : Math.round(Math.abs(delta) * scale);
                const isRecovery = delta >= 0;
                const color     = isNub
                  ? ZEN.colors.border
                  : isRecovery
                  ? ZEN.colors.recovery
                  : ZEN.colors.stress;
                return (
                  <View
                    key={i}
                    style={{
                      width:        BAR_W,
                      marginRight:  BAR_GAP,
                      height:       HALF_H * 2 + 1,
                      justifyContent: 'center',
                      alignItems:   'center',
                    }}
                  >
                    {/* Above-centre bar (recovery) */}
                    <View style={{ height: HALF_H, justifyContent: 'flex-end', width: BAR_W }}>
                      {isRecovery && (
                        <View style={{ width: BAR_W, height: barH, backgroundColor: color, borderRadius: 2 }} />
                      )}
                    </View>
                    {/* Centre line pixel */}
                    <View style={{ width: BAR_W, height: 1, backgroundColor: 'rgba(255,255,255,0.25)' }} />
                    {/* Below-centre bar (stress) */}
                    <View style={{ height: HALF_H, justifyContent: 'flex-start', width: BAR_W }}>
                      {!isRecovery && (
                        <View style={{ width: BAR_W, height: barH, backgroundColor: color, borderRadius: 2 }} />
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          </View>

          {/* X-axis time labels */}
          <View style={{ flexDirection: 'row', marginTop: 4, height: 14, position: 'relative' }}>
            {valid.map((w, i) => (
              i % labelStep === 0 ? (
                <View
                  key={i}
                  style={{
                    position: 'absolute',
                    left: Math.max(0, i * (BAR_W + BAR_GAP) - 16),
                    width: 36,
                    alignItems: 'center',
                  }}
                >
                  <Text style={dwc.xLabel}>{fmtTime(w.window_start)}</Text>
                </View>
              ) : null
            ))}
          </View>
        </View>
      </ScrollView>

      {/* Baseline label */}
      <Text style={dwc.baseline}>Baseline avg: {Math.round(morningAvg)} ms</Text>
    </SurfaceCard>
  );
}

// DivergingWindowChart styles (dwc)
const dwc = StyleSheet.create({
  card:        { gap: 4 },
  eyebrow:     { marginBottom: 0 },
  empty:       { fontSize: 13, color: ZEN.colors.textMuted, textAlign: 'center', paddingVertical: 32 },
  legend:      { flexDirection: 'row', gap: 12, marginTop: 2 },
  legendItem:  { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot:   { width: 7, height: 7, borderRadius: 3.5 },
  legendText:  { fontSize: 10, color: ZEN.colors.textMuted, letterSpacing: 0.3 },
  gridLine:    {
    position:        'absolute',
    left:            0,
    right:           0,
    height:          1,
    borderTopWidth:  1,
    borderColor:     ZEN.colors.border,
  },
  xLabel:      { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'center', width: 36 },
  baseline:    { fontSize: 10, color: ZEN.colors.textMuted, marginTop: 6, textAlign: 'right' },
});

// CombinedBalanceChart styles (cbc)
const cbc = StyleSheet.create({
  card: { gap: 8, paddingBottom: 4 },
  header: { flexDirection: 'column', alignItems: 'flex-start', gap: 2 },
  legend: { flexDirection: 'row', gap: 12 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot: { width: 7, height: 7, borderRadius: 3.5 },
  legendLabel: { fontSize: 10, color: 'rgba(255,255,255,0.45)', letterSpacing: 0.3 },
  empty: { alignItems: 'center', paddingVertical: 32, gap: 6 },
  emptyText: { fontSize: 13, color: 'rgba(255,255,255,0.40)', fontWeight: '500' },
  emptyHint: { fontSize: 11, color: 'rgba(255,255,255,0.22)' },
  xLabel: { fontSize: 8, color: 'rgba(255,255,255,0.38)', textAlign: 'center', width: 36 },
});

// ════════════════════════════════════════════════════════════════════════════
// IV. Plan components
// ════════════════════════════════════════════════════════════════════════════

// MiniProgress — small SVG ring showing adherence %
interface MiniProgressProps { value: number; }

export function MiniProgress({ value }: MiniProgressProps) {
  const size   = 52;
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circ   = 2 * Math.PI * radius;
  const offset = circ * (1 - Math.min(1, Math.max(0, value / 100)));
  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
        style={{ transform: [{ rotate: '-90deg' }] }}>
        <Circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={ZEN.colors.border} strokeWidth={stroke}
        />
        <Circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={ZEN.colors.recovery} strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${circ} ${circ}`}
          strokeDashoffset={offset}
        />
      </Svg>
      <View style={[StyleSheet.absoluteFillObject, mp.center]}>
        <Text style={mp.value}>{value}%</Text>
      </View>
    </View>
  );
}

// PlanActivityCard — wraps a PlanItem
export interface ZenPlanItem {
  id: string;
  title: string;
  duration_minutes: number;
  priority: 'must_do' | 'recommended' | 'optional';
  rationale: string;
  has_evidence: boolean;
  target_start_time?: string | null;
  adherence_score?: number | null;
}

export function PlanActivityCard({
  item,
  onPress,
}: {
  item: ZenPlanItem;
  onPress?: () => void;
}) {
  const borderColor = item.priority === 'must_do'
    ? 'rgba(57,226,125,0.30)'
    : ZEN.colors.border;
  const dotColor    = item.priority === 'must_do'
    ? ZEN.colors.recovery
    : item.priority === 'recommended'
    ? ZEN.colors.readiness
    : ZEN.colors.textMuted;
  const doneAlpha   = item.has_evidence ? 0.45 : 1;

  return (
    <TouchableOpacity
      style={[pa.card, { borderColor, opacity: doneAlpha }]}
      activeOpacity={0.8}
      onPress={onPress}
      disabled={!onPress && !item.has_evidence}
    >
      <View style={pa.row}>
        {/* Priority dot */}
        <View style={[pa.dot, { backgroundColor: dotColor }]} />

        <View style={pa.middle}>
          <Text style={pa.title}>{item.title}</Text>
          <Text style={pa.meta}>
            {item.duration_minutes}m
            {item.target_start_time
              ? ` · ${new Date('1970-01-01T' + item.target_start_time).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })}`
              : ''}
          </Text>
          <Text style={pa.rationale} numberOfLines={2}>{item.rationale}</Text>
        </View>

        {/* Done badge */}
        {item.has_evidence ? (
          <View style={pa.doneBadge}>
            <Text style={pa.doneText}>✓</Text>
          </View>
        ) : null}
      </View>
    </TouchableOpacity>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// V. Coach components
// ════════════════════════════════════════════════════════════════════════════

export interface ZenChatMessage {
  id?: string;
  role: 'user' | 'coach';
  content: string;
  isSynthesis?: boolean;
}

export function ChatBubble({ message }: { message: ZenChatMessage }) {
  const isUser     = message.role === 'user';
  const isSynth    = message.isSynthesis;

  if (isSynth) {
    return (
      <View style={cb.synthCard}>
        <SectionEyebrow>Morning brief</SectionEyebrow>
        <Text style={cb.synthBody}>{message.content}</Text>
      </View>
    );
  }

  return (
    <View style={[cb.bubble, isUser ? cb.userBubble : cb.coachBubble]}>
      <Text style={[cb.text, isUser ? cb.userText : cb.coachText]}>
        {message.content}
      </Text>
    </View>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// VI. History components
// ════════════════════════════════════════════════════════════════════════════

export interface HistoryDay {
  day: string;        // formatted date label e.g. "Mon, Mar 10"
  date: string;       // ISO date "2026-03-10"
  stress: number | null;
  recovery: number | null;
  readiness: number | null;
  dayType?: string;
}

export function HistoryDayCard({
  day,
  expanded = false,
  onPress,
}: {
  day: HistoryDay;
  expanded?: boolean;
  onPress?: () => void;
}) {
  return (
    <TouchableOpacity
      style={[hd.card, expanded && hd.cardExpanded]}
      activeOpacity={0.8}
      onPress={onPress}
    >
      <View style={hd.row}>
        {/* Date */}
        <Text style={hd.dayLabel}>{day.day}</Text>

        {/* Score chips */}
        <View style={hd.chips}>
          <View style={hd.chip}>
            <Text style={[hd.chipNum, { color: ZEN.colors.stress }]}>
              {day.stress !== null ? Math.round(day.stress) : '—'}
            </Text>
            <Text style={hd.chipLabel}>S</Text>
          </View>
          <View style={hd.chip}>
            <Text style={[hd.chipNum, { color: ZEN.colors.recovery }]}>
              {day.recovery !== null ? Math.round(day.recovery) : '—'}
            </Text>
            <Text style={hd.chipLabel}>R</Text>
          </View>
          <View style={hd.chip}>
            <Text style={[hd.chipNum, { color: ZEN.colors.readiness }]}>
              {day.readiness !== null ? Math.round(day.readiness) : '—'}
            </Text>
            <Text style={hd.chipLabel}>Rd</Text>
          </View>
        </View>

        <Text style={hd.arrow}>›</Text>
      </View>

      {expanded ? (
        <View style={hd.expandedDots}>
          {(['stress', 'recovery', 'readiness'] as const).map((k) => {
            const v   = day[k];
            const col = k === 'stress' ? ZEN.colors.stress : k === 'recovery' ? ZEN.colors.recovery : ZEN.colors.readiness;
            const w   = v !== null ? `${Math.round(v)}%` : '0%';
            return (
              <View key={k} style={hd.barRow}>
                <Text style={hd.barLabel}>{k.charAt(0).toUpperCase() + k.slice(1)}</Text>
                <View style={hd.barTrack}>
                  <View style={[hd.barFill, { width: w as any, backgroundColor: col }]} />
                </View>
                <Text style={[hd.barVal, { color: col }]}>{v !== null ? Math.round(v) : '—'}</Text>
              </View>
            );
          })}
        </View>
      ) : null}
    </TouchableOpacity>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Styles: new components
// ════════════════════════════════════════════════════════════════════════════

// RecoveryChartCard styles (ch2)
const ch2 = StyleSheet.create({
  card:       { padding: 16 },
  empty:      { color: ZEN.colors.textMuted, fontSize: 13, textAlign: 'center', paddingVertical: 40 },
  legend:     { flexDirection: 'row', alignItems: 'center', marginTop: 10, gap: 4 },
  legendDot:  { width: 8, height: 8, borderRadius: 4 },
  legendText: { fontSize: 11, color: ZEN.colors.textMuted },
  yLabel:     { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'right', width: 24 },
  yUnit:      { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'right', width: 24 },
  xLabel:     { fontSize: 8, color: ZEN.colors.textMuted, textAlign: 'center', width: 36 },
});

// RecoveryEventRow styles (re)
const re = StyleSheet.create({
  card: { padding: 16, marginBottom: 0 },
  row: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 },
  left: { flex: 1 },
  topRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  time: { fontSize: 12, textTransform: 'uppercase', letterSpacing: 1.8, color: ZEN.colors.textQuiet },
  tagPill: {
    borderRadius: ZEN.radius.pill, borderWidth: 1, borderColor: ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface, paddingHorizontal: 8, paddingVertical: 2,
  },
  tagPillText: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textFaint },
  tagCta: {
    borderRadius: ZEN.radius.pill, borderWidth: 1,
    borderColor: 'rgba(57,226,125,0.30)', backgroundColor: 'rgba(57,226,125,0.10)',
    paddingHorizontal: 14, paddingVertical: 8,
  },
  tagCtaText: { fontSize: 12, fontWeight: '600', color: '#70EDAA' },
  label: { fontSize: 17, fontWeight: '500', letterSpacing: -0.34, color: ZEN.colors.textAlmost },
  desc: { marginTop: 8, fontSize: 13, lineHeight: 20, color: ZEN.colors.textSubtle },
  taggedRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  taggedCheck: { fontSize: 16, color: ZEN.colors.recovery, fontWeight: '700' },
  right: { alignItems: 'flex-end' },
  contribLabel: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.8, color: ZEN.colors.textDim },
  contribValue: { marginTop: 8, fontSize: 24, fontWeight: '600', letterSpacing: -0.7, color: ZEN.colors.recovery },
});

// BreakdownRow styles (br)
const br = StyleSheet.create({
  row: {
    flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between',
    gap: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: ZEN.colors.border,
  },
  rowHighlight: {
    backgroundColor: 'rgba(242,209,76,0.04)',
    borderRadius:    ZEN.radius.tab,
    paddingHorizontal: 10,
  },
  left:  { flex: 1 },
  label: { fontSize: 14, fontWeight: '500', color: ZEN.colors.textBody },
  note:  { marginTop: 4, fontSize: 12, lineHeight: 18, color: ZEN.colors.textSecondary },
  value: { fontSize: 22, fontWeight: '600', letterSpacing: -0.5, color: ZEN.colors.white },
  valueHighlight: { color: ZEN.colors.readiness },
});

// MiniProgress styles (mp)
const mp = StyleSheet.create({
  center: { alignItems: 'center', justifyContent: 'center' },
  value:  { fontSize: 11, fontWeight: '600', color: ZEN.colors.textBody },
});

// PlanActivityCard styles (pa)
const pa = StyleSheet.create({
  card: {
    borderRadius: ZEN.radius.card, borderWidth: 1, backgroundColor: ZEN.colors.surfaceSoft,
    padding: 14,
  },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  middle: { flex: 1 },
  title: { fontSize: 16, fontWeight: '500', letterSpacing: -0.32, color: ZEN.colors.textAlmost },
  meta: {
    marginTop: 4, fontSize: 12, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textMuted,
  },
  rationale: { marginTop: 6, fontSize: 13, lineHeight: 20, color: ZEN.colors.textSecondary },
  doneBadge: {
    width: 28, height: 28, borderRadius: 14,
    backgroundColor: 'rgba(57,226,125,0.15)', borderWidth: 1,
    borderColor: 'rgba(57,226,125,0.35)', alignItems: 'center', justifyContent: 'center',
  },
  doneText: { fontSize: 13, color: ZEN.colors.recovery, fontWeight: '700' },
});

// ChatBubble styles (cb)
const cb = StyleSheet.create({
  synthCard: {
    borderRadius: ZEN.radius.section, borderWidth: 1, borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surface, padding: 16, marginBottom: 4,
  },
  synthBody: { marginTop: 10, fontSize: 15, lineHeight: 26, color: ZEN.colors.textBody },
  bubble: {
    maxWidth: '78%', borderRadius: ZEN.radius.card, paddingHorizontal: 14, paddingVertical: 10,
  },
  userBubble: {
    alignSelf: 'flex-end', backgroundColor: ZEN.colors.surfaceStrong,
    borderWidth: 1, borderColor: ZEN.colors.borderStrong,
  },
  coachBubble: {
    alignSelf: 'flex-start', backgroundColor: ZEN.colors.surface,
    borderWidth: 1, borderColor: ZEN.colors.border,
  },
  text:      { fontSize: 15, lineHeight: 24 },
  userText:  { color: ZEN.colors.textNear },
  coachText: { color: ZEN.colors.textBody },
});

// HistoryDayCard styles (hd)
const hd = StyleSheet.create({
  card: {
    borderRadius: ZEN.radius.card, borderWidth: 1, borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft, padding: 14,
  },
  cardExpanded: { borderColor: ZEN.colors.borderStrong },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  dayLabel: { flex: 1, fontSize: 14, fontWeight: '500', color: ZEN.colors.textBody },
  chips: { flexDirection: 'row', gap: 12 },
  chip: { alignItems: 'center', gap: 2 },
  chipNum: { fontSize: 17, fontWeight: '700', letterSpacing: -0.4 },
  chipLabel: {
    fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.4, color: ZEN.colors.textMuted,
  },
  arrow: { fontSize: 18, color: ZEN.colors.textMuted, paddingLeft: 4 },
  expandedDots: { marginTop: 14, gap: 8 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  barLabel: {
    width: 80, fontSize: 12, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textQuiet,
  },
  barTrack: {
    flex: 1, height: 4, borderRadius: 2, backgroundColor: ZEN.colors.border, overflow: 'hidden',
  },
  barFill: { height: 4, borderRadius: 2 },
  barVal: { width: 28, fontSize: 13, fontWeight: '600', textAlign: 'right' },
});


// ════════════════════════════════════════════════════════════════════════════
// VII. Plan v2 components
// ════════════════════════════════════════════════════════════════════════════

// PlanMiniRing — progress ring with freeform string label (not just %)
export function PlanMiniRing({ progress, label, color = ZEN.colors.recovery }: { progress: number; label: string; color?: string }) {
  const size   = 56;
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circ   = 2 * Math.PI * radius;
  const active = circ * Math.min(1, Math.max(0, progress / 100));
  const inactive = circ - active;
  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
        style={{ transform: [{ rotate: '-90deg' }] }}>
        <Circle cx={size/2} cy={size/2} r={radius} fill="none"
          stroke="rgba(255,255,255,0.12)" strokeWidth={stroke} />
        <Circle cx={size/2} cy={size/2} r={radius} fill="none"
          stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${active} ${inactive}`} />
      </Svg>
      <View style={[StyleSheet.absoluteFillObject, { alignItems: 'center', justifyContent: 'center' }]}>
        <Text style={{ fontSize: 12, fontWeight: '600', color: ZEN.colors.white }}>{label}</Text>
      </View>
    </View>
  );
}

// MetricStatCard — 2-column stat card used in plan detail sheet & health monitor
export interface MetricStat { label: string; value: string; hint?: string; }

export function MetricStatCard({ stat }: { stat: MetricStat }) {
  return (
    <View style={msc.card}>
      <Text style={msc.label}>{stat.label}</Text>
      <Text style={msc.value}>{stat.value}</Text>
      {stat.hint ? <Text style={msc.hint}>{stat.hint}</Text> : null}
    </View>
  );
}

const msc = StyleSheet.create({
  card:  { flex: 1, borderRadius: 18, borderWidth: 1, borderColor: ZEN.colors.border, backgroundColor: ZEN.colors.surface, padding: 14 },
  label: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textMuted },
  value: { marginTop: 8, fontSize: 24, fontWeight: '600', letterSpacing: -0.8, color: ZEN.colors.white },
  hint:  { marginTop: 6, fontSize: 12, color: ZEN.colors.textQuiet },
});

// ════════════════════════════════════════════════════════════════════════════
// VIII. History v2 components
// ════════════════════════════════════════════════════════════════════════════

export interface TrendPoint {
  label: string;
  stress: number;
  recovery: number;
  readiness: number;
}

// TrendPolyChart — multi-line SVG chart for history trends
export function TrendPolyChart({ data }: { data: TrendPoint[] }) {
  if (!data || data.length < 2) return null;
  const W = 320, H = 180, padX = 8, padTop = 10, padBottom = 30;
  const iW = W - padX * 2, iH = H - padTop - padBottom;
  const pts = (key: keyof TrendPoint) =>
    data.map((d, i) => {
      const x = padX + (i / (data.length - 1)) * iW;
      const v = typeof d[key] === 'number' ? (d[key] as number) : 0;
      const y = padTop + (1 - v / 100) * iH;
      return `${x},${y}`;
    }).join(' ');
  return (
    <View style={tc.wrap}>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        {[0.2, 0.4, 0.6, 0.8].map(r => (
          <Line key={r} x1={padX} x2={W - padX}
            y1={padTop + iH * r} y2={padTop + iH * r}
            stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
        ))}
        <Polyline fill="none" stroke={ZEN.colors.stress} strokeWidth="3"
          strokeLinecap="round" strokeLinejoin="round" points={pts('stress')} />
        <Polyline fill="none" stroke={ZEN.colors.recovery} strokeWidth="3"
          strokeLinecap="round" strokeLinejoin="round" points={pts('recovery')} />
        <Polyline fill="none" stroke={ZEN.colors.readiness} strokeWidth="3"
          strokeLinecap="round" strokeLinejoin="round" points={pts('readiness')} />
      </Svg>
      <View style={tc.labels}>
        {data.map(d => (
          <Text key={d.label} style={tc.labelText}>{d.label}</Text>
        ))}
      </View>
    </View>
  );
}

const tc = StyleSheet.create({
  wrap:      { borderRadius: 20, borderWidth: 1, borderColor: ZEN.colors.border, backgroundColor: ZEN.colors.surface, paddingHorizontal: 8, paddingVertical: 8 },
  labels:    { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  labelText: { flex: 1, fontSize: 11, textAlign: 'center', textTransform: 'uppercase', letterSpacing: 1.4, color: ZEN.colors.textMuted },
});

// ReportCardRow — score letter + progress bar
export function ReportCardRow({ label, value, bar }: { label: string; value: string; bar: number }) {
  return (
    <View style={rcr.card}>
      <View style={rcr.top}>
        <Text style={rcr.label}>{label}</Text>
        <Text style={rcr.grade}>{value}</Text>
      </View>
      <View style={rcr.track}>
        <View style={[rcr.fill, { width: `${Math.min(100, bar)}%` as any }]} />
      </View>
    </View>
  );
}

const rcr = StyleSheet.create({
  card:  { borderRadius: 16, borderWidth: 1, borderColor: ZEN.colors.border, backgroundColor: 'rgba(255,255,255,0.02)', padding: 12 },
  top:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  label: { fontSize: 14, color: ZEN.colors.textBody },
  grade: { fontSize: 16, fontWeight: '600', color: ZEN.colors.white },
  track: { marginTop: 10, height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden' },
  fill:  { height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.80)' },
});

// ════════════════════════════════════════════════════════════════════════════
// IX. Health monitor components
// ════════════════════════════════════════════════════════════════════════════

// HealthLineChart — single-line sparkline chart
export function HealthLineChart({ values }: { values: number[] }) {
  if (!values || values.length < 2) return null;
  const W = 320, H = 120, padX = 6, padTop = 14, padBottom = 16;
  const max = Math.max(...values), min = Math.min(...values);
  const rng = Math.max(max - min, 1);
  const points = values.map((v, i) => {
    const x = padX + (i / (values.length - 1)) * (W - padX * 2);
    const y = padTop + (1 - (v - min) / rng) * (H - padTop - padBottom);
    return `${x},${y}`;
  }).join(' ');
  return (
    <View style={hlc.wrap}>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        <Polyline fill="none" stroke={ZEN.colors.stress} strokeWidth="3"
          strokeLinecap="round" strokeLinejoin="round" points={points} />
      </Svg>
    </View>
  );
}

const hlc = StyleSheet.create({
  wrap: { borderRadius: 20, borderWidth: 1, borderColor: ZEN.colors.border, backgroundColor: ZEN.colors.surface, paddingHorizontal: 8, paddingVertical: 8 },
});

// HealthMetricCard — metric with big value + status line
export interface HealthMetric {
  label: string;
  value: string;
  unit: string;
  status: string;
  statusOk: boolean;  // true=green, false=yellow
}

export function HealthMetricCard({ metric }: { metric: HealthMetric }) {
  const statusColor = metric.statusOk ? ZEN.colors.recovery : ZEN.colors.readiness;
  return (
    <View style={hmc.card}>
      <Text style={hmc.label}>{metric.label}</Text>
      <View style={hmc.valueRow}>
        <Text style={hmc.value}>{metric.value}</Text>
        <Text style={hmc.unit}>{metric.unit}</Text>
      </View>
      <Text style={[hmc.status, { color: statusColor }]}>{metric.status}</Text>
    </View>
  );
}

const hmc = StyleSheet.create({
  card:     { flex: 1, borderRadius: 18, borderWidth: 1, borderColor: ZEN.colors.border, backgroundColor: ZEN.colors.surface, padding: 14 },
  label:    { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textMuted },
  valueRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 4, marginTop: 10 },
  value:    { fontSize: 32, fontWeight: '600', letterSpacing: -1.5, color: ZEN.colors.white },
  unit:     { fontSize: 14, color: ZEN.colors.textLabel, marginBottom: 4 },
  status:   { marginTop: 10, fontSize: 12 },
});
