/**
 * Shared TanStack Query client.
 *
 * This file is the single source of truth for server-state caching. Screens
 * should prefer `useQuery(['key'], fetcher)` over ad-hoc useEffect polling —
 * React Query dedupes parallel calls, caches responses, and cancels
 * in-flight requests on unmount via the provided AbortSignal.
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Screens refetch on mount if data is older than this.
      staleTime: 60 * 1000,
      // Background refetch interval for Home-style live data is handled
      // explicitly per-query via `refetchInterval`.
      refetchOnWindowFocus: false,
      // Transient network failures are already handled in the Axios
      // interceptor; React Query's own retry is a safety-net only.
      retry: 1,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4000),
    },
    mutations: {
      retry: 0,
    },
  },
});
