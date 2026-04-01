import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors, Spacing, Radius, Typography } from '../theme';

interface CoachMessageProps {
  role: 'assistant' | 'user';
  text: string;
  isSynthesis?: boolean;
}

export default function CoachMessage({ role, text, isSynthesis }: CoachMessageProps) {
  const isUser = role === 'user';
  return (
    <View style={[styles.wrapper, isUser ? styles.wrapperUser : styles.wrapperAssistant]}>
      {!isUser && (
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>Z</Text>
        </View>
      )}
      <View
        style={[
          styles.bubble,
          isUser ? styles.bubbleUser : styles.bubbleAssistant,
          isSynthesis && styles.bubbleSynthesis,
        ]}
      >
        <Text
          style={[
            styles.text,
            isUser ? styles.textUser : styles.textAssistant,
            isSynthesis && styles.textSynthesis,
          ]}
        >
          {text}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { flexDirection: 'row', alignItems: 'flex-end', gap: Spacing.sm, marginVertical: 4 },
  wrapperUser: { flexDirection: 'row-reverse' },
  wrapperAssistant: {},
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Colors.coachDim ?? '#2A1F3D',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Colors.coach,
  },
  avatarText: { fontSize: 12, fontWeight: '700', color: Colors.coach },
  bubble: {
    maxWidth: '80%',
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Radius.lg,
  },
  bubbleUser: {
    backgroundColor: Colors.readiness,
    borderBottomRightRadius: 4,
  },
  bubbleAssistant: {
    backgroundColor: Colors.surface2,
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  bubbleSynthesis: {
    backgroundColor: Colors.coachDim ?? '#2A1F3D',
    borderColor: Colors.coach,
  },
  text: { fontSize: 15, lineHeight: 22 },
  textUser: { color: Colors.black, fontWeight: '500' },
  textAssistant: { color: Colors.text },
  textSynthesis: { color: Colors.coach, fontStyle: 'italic' },
});
