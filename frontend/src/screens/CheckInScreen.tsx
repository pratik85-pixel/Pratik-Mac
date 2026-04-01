import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ActivityIndicator, Alert, TextInput, KeyboardAvoidingView, Platform, ScrollView,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import axios from 'axios';
import { submitCheckIn } from '../api/plan';
import ScreenWrapper from '../components/ScreenWrapper';
import { Colors, Spacing, Typography, Radius } from '../theme';
import type { ProfileStackParamList } from '../navigation/AppNavigator';

function ScoreRow({
  label, value, onChange, color, description,
}: {
  label: string; value: number;
  onChange: (v: number) => void;
  color: string; description: string;
}) {
  const adjust = (delta: number) => {
    const next = Math.min(10, Math.max(1, value + delta));
    if (next !== value) {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      onChange(next);
    }
  };

  return (
    <View style={srStyles.block}>
      <Text style={srStyles.label}>{label}</Text>
      <Text style={srStyles.desc}>{description}</Text>
      <View style={srStyles.row}>
        <TouchableOpacity style={srStyles.btn} onPress={() => adjust(-1)} activeOpacity={0.7}>
          <Ionicons name="remove" size={20} color={Colors.textSecondary} />
        </TouchableOpacity>
        <Text style={[srStyles.num, { color }]}>{value}</Text>
        <TouchableOpacity style={srStyles.btn} onPress={() => adjust(1)} activeOpacity={0.7}>
          <Ionicons name="add" size={20} color={Colors.textSecondary} />
        </TouchableOpacity>
      </View>
      {/* Pip dots */}
      <View style={srStyles.pips}>
        {Array.from({ length: 10 }, (_, i) => (
          <TouchableOpacity
            key={i}
            style={[srStyles.pip, i < value && { backgroundColor: color }]}
            onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); onChange(i + 1); }}
          />
        ))}
      </View>
    </View>
  );
}

const srStyles = StyleSheet.create({
  block: { gap: 8 },
  label: { fontSize: 15, fontWeight: '600', color: Colors.text },
  desc: { fontSize: 12, color: Colors.textMuted },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  btn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: Colors.surface2, borderWidth: 1, borderColor: Colors.border,
    alignItems: 'center', justifyContent: 'center',
  },
  num: { fontSize: 36, fontWeight: '800', letterSpacing: -1, width: 60, textAlign: 'center' },
  pips: { flexDirection: 'row', gap: 4 },
  pip: {
    flex: 1, height: 4, borderRadius: 2,
    backgroundColor: Colors.surface2,
  },
});

export default function CheckInScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const [reactivity, setReactivity] = useState(5);
  const [focus, setFocus] = useState(5);
  const [recovery, setRecovery] = useState(5);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await submitCheckIn(reactivity, focus, recovery);
      Alert.alert('Check-in saved!', 'Thanks — your plan may update.', [
        { text: 'OK', onPress: () => nav.goBack() },
      ]);
    } catch {
      Alert.alert('Error', 'Could not save check-in. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <ScreenWrapper>
      <TopHeader
        title="Daily Check-In"
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      <View style={styles.content}>
        <Text style={styles.intro}>
          How does your body feel right now? Rate each on 1–10.
        </Text>

        <ScoreRow
          label="Stress Reactivity"
          value={reactivity}
          onChange={setReactivity}
          color={Colors.stress}
          description="How easily stressed or triggered do you feel?"
        />

        <ScoreRow
          label="Mental Focus"
          value={focus}
          onChange={setFocus}
          color={Colors.readiness}
          description="How sharp and present does your mind feel?"
        />

        <ScoreRow
          label="Physical Recovery"
          value={recovery}
          onChange={setRecovery}
          color={Colors.recovery}
          description="How rested and energised does your body feel?"
        />

        <TouchableOpacity
          style={styles.cta}
          onPress={save}
          disabled={saving}
          activeOpacity={0.8}
        >
          {saving
            ? <ActivityIndicator color={Colors.black} />
            : <Text style={styles.ctaText}>Save Check-In</Text>}
        </TouchableOpacity>
      </View>
    </ScreenWrapper>
  );
}

const styles = StyleSheet.create({
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm,
    borderBottomWidth: 1, borderBottomColor: Colors.border,
  },
  back: { padding: 6 },
  navTitle: { ...Typography.sectionTitle, fontSize: 16, color: Colors.text },
  content: { flex: 1, padding: Spacing.lg, gap: Spacing.xl },
  intro: { fontSize: 15, color: Colors.textSecondary, lineHeight: 22, fontStyle: 'italic' },
  cta: {
    backgroundColor: Colors.readiness, borderRadius: 14,
    paddingVertical: 18, alignItems: 'center', marginTop: 'auto' as any,
  },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
