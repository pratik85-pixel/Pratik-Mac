import { getClient } from '../api/client';
import { useState, useCallback, useEffect } from 'react';

export const useOutcomes = () => {
  const [weekly, setWeekly] = useState<any>(null);
  const [longitudinal, setLongitudinal] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOutcomes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [weeklyRes, longitudinalRes] = await Promise.all([
        getClient().get('/api/v1/outcomes/weekly'),
        getClient().get('/api/v1/outcomes/longitudinal'),
      ]);
      setWeekly(weeklyRes.data);
      setLongitudinal(longitudinalRes.data);
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOutcomes();
  }, [fetchOutcomes]);

  return { weekly, longitudinal, loading, error, refreshOutcomes: fetchOutcomes };
};
