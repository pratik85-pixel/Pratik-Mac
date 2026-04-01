import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, TextInput,
  Alert, ScrollView,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Colors } from '../theme';
import { getApiBase, saveApiBase, getUser, clear } from '../store/auth';
import { initClient, setApiBase } from '../api/client';
import type { ProfileStackParamList } from '../navigation/AppNavigator';
import { polarService } from '../services/PolarService';
import {
  ZenScreen, ZEN,
} from '../ui/zenflow-ui-kit';

export default function SettingsScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const [apiBase, setApiBaseState] = useState('');
  const [name, setNameState] = useState('');
  const [userId, setUserIdState] = useState('');
  // BLE diagnostics — live
  const [bleStatus, setBleStatus]         = useState(polarService.status);
  const [beatCount, setBeatCount]         = useState(polarService.beatCount);
  const [packetCount, setPacketCount]     = useState(polarService.packetCount);
  const [blockedCount, setBlockedCount]   = useState(polarService.blockedCount);
  const [lastFlush, setLastFlush]         = useState<Date | null>(polarService.lastFlushAt);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getApiBase().then((b) => setApiBaseState(b ?? 'http://192.168.1.33:8000'));
    getUser().then((u) => {
      setNameState(u?.name ?? '');
      setUserIdState(u?.userId ?? '');
    });

    // Subscribe to polar events
    const unsubStatus = polarService.subscribeStatus((s) => setBleStatus(s));
    const unsubBeat   = polarService.subscribeBeat(() => setBeatCount(polarService.beatCount));
    const unsubFlush  = polarService.subscribeFlush(() => setLastFlush(polarService.lastFlushAt));
    // Refresh counts every 2 s
    tickRef.current = setInterval(() => {
      setBeatCount(polarService.beatCount);
      setPacketCount(polarService.packetCount);
      setBlockedCount(polarService.blockedCount);
    }, 2000);

    return () => {
      unsubStatus(); unsubBeat(); unsubFlush();
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, []);

  const saveBaseUrl = async () => {
    const url = apiBase.trim().replace(/\/$/, '');
    if (!url.startsWith('http')) {
      Alert.alert('Invalid URL', 'Must start with http:// or https://');
      return;
    }
    await saveApiBase(url);       // persist to AsyncStorage
    await setApiBase(url);         // reinit axios client with new base
    Alert.alert('Saved', 'API base URL updated. Changes apply immediately.');
  };

  const confirmReset = () => {
    Alert.alert(
      'Reset everything?',
      'This erases your local profile and returns to onboarding. Your server data is untouched.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            await clear();
            nav.reset({ index: 0, routes: [{ name: 'Onboarding' as any }] });
          },
        },
      ],
    );
  };

  return (
    <ZenScreen scrollable={false}>
      <TopHeader
        title="Settings"
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* User info */}
        <Text style={styles.sectionTitle}>ACCOUNT</Text>
        <View style={styles.infoCard}>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Name</Text>
            <Text style={styles.infoVal}>{name || '—'}</Text>
          </View>
          <View style={[styles.infoRow, styles.infoRowLast]}>
            <Text style={styles.infoKey}>User ID</Text>
            <Text style={[styles.infoVal, styles.infoMono]} numberOfLines={1} ellipsizeMode="middle">
              {userId || '—'}
            </Text>
          </View>
        </View>

        {/* API Base */}
        <Text style={styles.sectionTitle}>API CONNECTION</Text>
        <Text style={styles.hint}>
          Point this at your running ZenFlow backend. Make sure your phone and computer are on the same WiFi.
        </Text>
        <View style={styles.inputRow}>
          <TextInput
            style={styles.input}
            value={apiBase}
            onChangeText={setApiBaseState}
            placeholder="http://192.168.1.xxx:8000"
            placeholderTextColor={Colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
          <TouchableOpacity style={styles.saveBtn} onPress={saveBaseUrl} activeOpacity={0.8}>
            <Text style={styles.saveBtnText}>Save</Text>
          </TouchableOpacity>
        </View>

        {/* BLE Diagnostics */}
        <Text style={styles.sectionTitle}>BLE DIAGNOSTICS</Text>
        <View style={styles.infoCard}>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Status</Text>
            <Text style={[styles.infoVal, {
              color:
                bleStatus === 'streaming' ? '#30D158' :
                bleStatus === 'connected' ? '#FFD60A' :
                bleStatus === 'no_signal' ? '#FF9F0A' :
                Colors.textMuted,
            }]}>
              {bleStatus === 'no_signal' ? 'no_signal ⚠︎ adjust sensor' : bleStatus}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Valid beats</Text>
            <Text style={[styles.infoVal, { color: beatCount > 0 ? '#30D158' : Colors.textMuted }]}>
              {beatCount}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Packets received</Text>
            <Text style={[styles.infoVal, { color: packetCount > 0 ? Colors.textSecondary : Colors.textMuted }]}>
              {packetCount}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Discarded (move/invalid)</Text>
            <Text style={[styles.infoVal, { color: blockedCount > 0 ? '#FF9F0A' : Colors.textMuted }]}>
              {blockedCount}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoKey}>Last flush</Text>
            <Text style={styles.infoVal}>
              {lastFlush ? lastFlush.toLocaleTimeString() : 'never'}
            </Text>
          </View>
          <View style={[styles.infoRow, styles.infoRowLast]}>
            <Text style={styles.infoKey}>Force flush</Text>
            <TouchableOpacity
              onPress={async () => {
                await polarService.flushNow();
                setLastFlush(polarService.lastFlushAt);
              }}
              style={styles.flushBtn}
              activeOpacity={0.7}
            >
              <Text style={styles.flushBtnText}>Flush now</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Reset */}
        <Text style={styles.sectionTitle}>DANGER ZONE</Text>
        <TouchableOpacity style={styles.resetBtn} onPress={confirmReset} activeOpacity={0.8}>
          <Text style={styles.resetText}>Reset app & return to onboarding</Text>
        </TouchableOpacity>

        {/* Version */}
        <Text style={styles.version}>ZenFlow Verity · v1.0.0</Text>
      </ScrollView>
    </ZenScreen>
  );
}

const styles = StyleSheet.create({
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingBottom: 16, marginBottom: 4,
    borderBottomWidth: 1, borderBottomColor: ZEN.colors.border,
  },
  navTitle: { fontSize: 16, fontWeight: '600', color: ZEN.colors.white },
  scroll: { padding: 20, gap: 20, paddingBottom: 40 },
  sectionTitle: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 2.4, color: ZEN.colors.textMuted, marginTop: 8 },
  infoCard: {
    backgroundColor: ZEN.colors.surface, borderRadius: 16,
    borderWidth: 1, borderColor: ZEN.colors.border, overflow: 'hidden',
  },
  infoRow: {
    flexDirection: 'row', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: ZEN.colors.border,
  },
  infoRowLast: { borderBottomWidth: 0 },
  infoKey: { fontSize: 14, color: ZEN.colors.textMuted },
  infoVal: { fontSize: 14, color: ZEN.colors.textSecondary, maxWidth: '60%', textAlign: 'right' },
  infoMono: { fontFamily: 'monospace', fontSize: 12 },
  hint: { fontSize: 13, color: ZEN.colors.textMuted, lineHeight: 20 },
  inputRow: { flexDirection: 'row', gap: 8 },
  input: {
    flex: 1, backgroundColor: ZEN.colors.surface,
    borderRadius: 12, borderWidth: 1, borderColor: ZEN.colors.border,
    paddingHorizontal: 16, paddingVertical: 12,
    fontSize: 14, color: ZEN.colors.white,
  },
  saveBtn: {
    backgroundColor: ZEN.colors.readiness, borderRadius: 12,
    paddingHorizontal: 16, justifyContent: 'center',
  },
  saveBtnText: { fontSize: 14, fontWeight: '700', color: '#000' },
  resetBtn: {
    backgroundColor: ZEN.colors.stressTagBg, borderRadius: 12,
    borderWidth: 1, borderColor: ZEN.colors.stress + '44',
    padding: 16, alignItems: 'center',
  },
  resetText: { fontSize: 15, fontWeight: '600', color: ZEN.colors.stress },
  flushBtn: {
    backgroundColor: ZEN.colors.surface, borderRadius: 8,
    borderWidth: 1, borderColor: ZEN.colors.border,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  flushBtnText: { fontSize: 12, fontWeight: '600', color: ZEN.colors.readiness },
  version: { fontSize: 12, color: ZEN.colors.textMuted, textAlign: 'center' },
});
