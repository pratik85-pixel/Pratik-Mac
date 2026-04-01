import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import 'react-native-get-random-values';
import { v4 as uuidv4 } from 'uuid';
import { Colors, Spacing, Typography, Radius } from '../../theme';
import { saveUser } from '../../store/auth';
import { setUserId } from '../../api/client';
import { updateHabits, rebuildProfile } from '../../api/endpoints';

function buildHabits(params: any, userName: string) {
  return {
    name:             userName,
    movement_enjoyed: params.movement ?? [],
    decompress_via:   params.decompress ?? [],
    goal:             params.goal ?? null,
    typical_day:      params.dayType ?? null,
    alcohol:          params.lifestyle?.alcohol ?? null,
    caffeine:         params.lifestyle?.caffeine ?? null,
    sleep_schedule:   params.lifestyle?.sleep ?? null,
  };
}

export default function Step8Name() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);

  const canContinue = name.trim().length >= 2;

  const finish = async () => {
    if (!canContinue || loading) return;
    setLoading(true);
    try {
      const userId = uuidv4();

      setUserId(userId);
      await saveUser(userId, name.trim());

      const habits = buildHabits(route.params ?? {}, name.trim());
      await updateHabits(habits).catch(() => {/* silent */});
      await rebuildProfile().catch(() => {/* silent — profile screen will retry */});

      nav.reset({ index: 0, routes: [{ name: 'Main' as any }] });
    } catch (e) {
      Alert.alert('Oops', 'Could not save your profile. Check the API address in Settings.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <Text style={styles.step}>7 of 7</Text>
        <Text style={styles.title}>What should we call you?</Text>
        <Text style={styles.sub}>Just a first name is fine.</Text>
      </View>

      <TextInput
        style={styles.input}
        placeholder="e.g. Alex"
        placeholderTextColor={Colors.textMuted}
        value={name}
        onChangeText={setName}
        autoFocus
        autoCapitalize="words"
        returnKeyType="done"
        onSubmitEditing={finish}
      />

      <View style={styles.bottom}>
        <TouchableOpacity
          style={[styles.cta, !canContinue && styles.ctaDisabled]}
          onPress={finish}
          disabled={!canContinue || loading}
          activeOpacity={0.8}
        >
          {loading
            ? <ActivityIndicator color={Colors.black} />
            : <Text style={styles.ctaText}>Start ZenFlow</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1, backgroundColor: Colors.black,
    paddingHorizontal: Spacing.lg, paddingTop: 80, paddingBottom: 56, gap: Spacing.xl,
  },
  header: { gap: 8 },
  step: { ...Typography.label, color: Colors.textMuted },
  title: { fontSize: 32, fontWeight: '800', letterSpacing: -1, color: Colors.text },
  sub: { ...Typography.bodySmall, color: Colors.textSecondary },
  input: {
    backgroundColor: Colors.surface2, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border,
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.md,
    fontSize: 22, fontWeight: '600', color: Colors.text,
    letterSpacing: -0.3,
  },
  bottom: { flex: 1, justifyContent: 'flex-end' },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center' },
  ctaDisabled: { opacity: 0.35 },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
