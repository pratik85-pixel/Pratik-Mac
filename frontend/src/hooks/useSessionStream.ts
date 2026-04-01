import { getApiBase, getUserId } from '../store/auth';
import { useState, useEffect, useCallback, useRef } from 'react';

const MAX_SESSION_MESSAGES = 200;

export const useSessionStream = (sessionId: string | null) => {
  const [isConnected, setIsConnected] = useState(false);
  const [messages, setMessages] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(async () => {
    if (!sessionId) return;

    const userId = await getUserId();
    if (!userId) {
      setError('No user ID — complete onboarding first');
      return;
    }

    const apiBase = await getApiBase() ?? 'https://api-production-8195d.up.railway.app';
    const wsBase = apiBase.replace(/^https:\/\//, 'wss://').replace(/^http:\/\//, 'ws://');
    const wsUrl = `${wsBase}/api/v1/sessions/ws/${sessionId}?user_id=${userId}`;
    
    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setMessages((prev) => {
          const next = [...prev, data];
          return next.length > MAX_SESSION_MESSAGES ? next.slice(-MAX_SESSION_MESSAGES) : next;
        });
      } catch (err) {
        setMessages((prev) => {
          const next = [...prev, event.data];
          return next.length > MAX_SESSION_MESSAGES ? next.slice(-MAX_SESSION_MESSAGES) : next;
        });
      }
    };

    ws.onerror = () => {
      setError('WebSocket error occurred');
    };

    ws.onclose = () => {
      setIsConnected(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [sessionId]);

  useEffect(() => {
    if (sessionId) {
      let cleanup: (() => void) | undefined;
      connect().then((fn) => { cleanup = fn; });
      return () => { if (cleanup) cleanup(); };
    }
  }, [sessionId, connect]);

  const sendMessage = useCallback((data: any) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data));
    } else {
      setError('Cannot send message: WebSocket is not connected');
    }
  }, [isConnected]);

  return { isConnected, messages, error, sendMessage };
};
