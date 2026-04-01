import { getClient } from '../api/client';
import { useState, useCallback } from 'react';

export const useDailySummary = () => {
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDailySummary = useCallback(async (date: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getClient().get(`/tracking/daily-summary/${date}`);
      setSummary(res.data);
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setSummary(null);
        return;
      }
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  return { summary, loading, error, fetchDailySummary };
};
