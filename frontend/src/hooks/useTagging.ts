import { getClient } from '../api/client';
import { useState, useCallback } from 'react';

export const useTagging = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tagWindow = useCallback(async (
    windowId: string,
    windowType: 'stress' | 'recovery',
    slug: string,
  ) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getClient().post('/tagging/tag', {
        window_id: windowId,
        window_type: windowType,
        slug,
      });
      return res.data;
    } catch (err: any) {
      setError(err.message || 'Unknown error');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { loading, error, tagWindow };
};
