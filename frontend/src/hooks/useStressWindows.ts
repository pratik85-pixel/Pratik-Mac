import { useState, useCallback, useEffect } from 'react';
import { getClient } from '../api/client';

export function useStressWindows(date: string) {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getClient().get(`/tracking/stress-windows/${date}`);
      setData(Array.isArray(res.data) ? res.data : []);
    } catch (err: any) {
      if (err?.response?.status !== 404) {
        console.warn('Error fetching stress windows', err);
      }
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [date]);

  // Auto-refresh every 5 minutes while the screen is mounted
  useEffect(() => {
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  return { data, loading, load };
}
