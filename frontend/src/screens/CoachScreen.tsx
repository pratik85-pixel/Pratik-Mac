import React, { useCallback, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList,
  KeyboardAvoidingView, Platform,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import EmptyState from '../components/EmptyState';
import VoiceInput from '../components/VoiceInput';
import { useCoach } from '../hooks/useCoach';
import {
  getNudge, getConversationHistory,
} from '../api/coach';
import type { ConversationTurn } from '../types';
import {
  ZEN,
  ZenScreen,
  SurfaceCard,
  SectionEyebrow,
  ChatBubble,
  type ZenChatMessage,
} from '../ui/zenflow-ui-kit';

export default function CoachScreen() {
  const [nudge, setNudge] = useState<string | null>(null);
  const { messages, sendMessage, setMessages, setConversationId } = useCoach();
  const flatRef = useRef<FlatList<any>>(null);

  useFocusEffect(useCallback(() => {
    loadNudge();
    loadHistory();
  }, []));

  const loadNudge = async () => {
    try { const res = await getNudge(); setNudge(res.data?.message ?? res.data?.nudge ?? null); } catch {}
  };
  const loadHistory = async () => {
    try {
      const res = await getConversationHistory();
      const turns: ConversationTurn[] = res.data?.turns ?? res.data ?? [];
      const conversationId = (res.data as any)?.conversation_id as string | undefined;
      if (conversationId) setConversationId(conversationId);
      const msgs: ZenChatMessage[] = turns.flatMap((t: any, i: number) => {
        if (t.role && t.content) return [{ id: `${t.role}-${i}`, role: t.role, content: t.content }];
        const out: ZenChatMessage[] = [];
        if (t.user_message) out.push({ id: `u-${i}`, role: 'user', content: t.user_message });
        if (t.assistant_message) out.push({ id: `a-${i}`, role: 'coach', content: t.assistant_message });
        return out;
      });
      if (msgs.length > 0) setMessages(msgs);
    } catch {}
  };

  const displayMessages = messages;

  return (
    <KeyboardAvoidingView
      style={s.kav}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={88}
    >
      <ZenScreen scrollable={false} style={s.flex}>
        {/* ── Header ── */}
        <View style={s.header}>
          <Text style={s.eyebrow}>Coach</Text>
          <Text style={s.title}>Conversation</Text>
        </View>

        {/* ── Nudge card ── */}
        {nudge ? (
          <SurfaceCard style={s.nudgeCard}>
            <SectionEyebrow>Today&#x2019;s nudge</SectionEyebrow>
            <Text style={s.nudgeText}>{nudge}</Text>
          </SurfaceCard>
        ) : null}

        {/* ── Chat thread ── */}
        <FlatList
          ref={flatRef}
          style={s.flex}
          data={displayMessages}
          keyExtractor={(m, i) => m.id ?? String(i)}
          contentContainerStyle={s.chatContent}
          showsVerticalScrollIndicator={false}
          renderItem={({ item }) => <ChatBubble message={item} />}
          ListEmptyComponent={
            <EmptyState
              icon="chatbubble-ellipses-outline"
              title="Ask me anything"
              message="I know your stress patterns, recovery, and what's worked for you."
            />
          }
          onContentSizeChange={() => flatRef.current?.scrollToEnd({ animated: false })}
        />

        {/* ── Input ── */}
        <VoiceInput onStopRecording={(text) => sendMessage(text)} />
      </ZenScreen>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  zenOuter:   { paddingHorizontal: 0, paddingTop: 0 },
  kav:        { flex: 1, paddingHorizontal: 20, paddingTop: 16 },
  flex:       { flex: 1 },
  header:     { marginBottom: 12 },
  eyebrow:    { fontSize: 10, textTransform: 'uppercase', letterSpacing: 3, color: ZEN.colors.textMuted },
  title:      { marginTop: 4, fontSize: 22, fontWeight: '600', letterSpacing: -0.5, color: ZEN.colors.white },
  nudgeCard:  { padding: 12, gap: 4, marginBottom: 8 },
  nudgeText:  { fontSize: 14, color: ZEN.colors.textLabel, lineHeight: 22 },
  chatContent: { paddingVertical: 8, gap: 4, flexGrow: 1 },
});
