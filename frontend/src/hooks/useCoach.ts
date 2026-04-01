import { useState, useCallback, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { sendConversationTurn } from '../api/coach';

const STORAGE_KEY = 'zenflow_coach_messages_v1';
const CONVERSATION_ID_KEY = 'zenflow_coach_conversation_id_v1';
const MAX_COACH_MESSAGES = 200;

export interface ChatMessage {
  id?: string;
  role: "user" | "coach";
  content: string;
  isSynthesis?: boolean;
}

function capMessages(ms: ChatMessage[]): ChatMessage[] {
  return ms.length > MAX_COACH_MESSAGES ? ms.slice(-MAX_COACH_MESSAGES) : ms;
}

export const useCoach = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Seed from AsyncStorage cache on first mount so messages survive tab navigation
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then((stored) => {
      if (stored) {
        try {
          const cached = capMessages(JSON.parse(stored) as ChatMessage[]);
          if (cached.length > 0) {
            setMessages((prev) => (prev.length === 0 ? cached : prev));
          }
        } catch {}
      }
    });
  }, []);

  useEffect(() => {
    AsyncStorage.getItem(CONVERSATION_ID_KEY).then((stored) => {
      if (stored) setConversationId(stored);
    });
  }, []);

  // Persist messages to AsyncStorage whenever they change
  useEffect(() => {
    if (messages.length > 0) {
      AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(capMessages(messages))).catch(() => {});
    }
  }, [messages]);

  useEffect(() => {
    if (conversationId) {
      AsyncStorage.setItem(CONVERSATION_ID_KEY, conversationId).catch(() => {});
    }
  }, [conversationId]);

  const sendMessage = useCallback(async (content: string) => {
    setLoading(true);
    setError(null);
    const newMessage: ChatMessage = { role: "user", content };
    setMessages((prev) => capMessages([...prev, newMessage]));

    try {
      const res = await sendConversationTurn(content, conversationId ?? undefined);
      const payload = res.data;
      if (payload?.conversation_id) setConversationId(payload.conversation_id);
      setMessages((prev) => capMessages([...prev, { role: 'coach', content: payload?.reply || payload?.follow_up || '...' }]));
    } catch (err: any) {
      setError(err.message || "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  return { messages, loading, error, sendMessage, setMessages, conversationId, setConversationId };
};
