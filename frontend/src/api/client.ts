import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// Default to local dev. User configures this in Settings.
const DEFAULT_BASE = 'https://api-production-8195d.up.railway.app';

let _client: AxiosInstance | null = null;
let _userId: string | null = null;

export async function initClient(baseOverride?: string): Promise<void> {
  const base = baseOverride ?? (await AsyncStorage.getItem('api_base')) ?? DEFAULT_BASE;
  const userId = await AsyncStorage.getItem('user_id');
  _userId = userId;
  _client = axios.create({
    baseURL: base,
    timeout: 15000,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      Pragma: 'no-cache',
    },
  });

  _client.interceptors.request.use((config) => {
    if (_userId) config.headers['X-User-Id'] = _userId;
    return config;
  });

  // Idempotent-GET retry with exponential backoff for transient network
  // failures (timeouts, 502/503/504). Non-idempotent methods are never
  // retried to avoid double writes.
  _client.interceptors.response.use(
    (resp) => resp,
    async (error: AxiosError) => {
      const cfg: (AxiosRequestConfig & { _retryCount?: number }) | undefined = error.config;
      const status = error.response?.status;
      const method = (cfg?.method ?? 'get').toLowerCase();
      const transient =
        error.code === 'ECONNABORTED' ||
        error.code === 'ERR_NETWORK' ||
        status === 502 ||
        status === 503 ||
        status === 504;
      const retriable = method === 'get' && transient;
      if (!cfg || !retriable) return Promise.reject(error);
      cfg._retryCount = (cfg._retryCount ?? 0) + 1;
      if (cfg._retryCount > 2) return Promise.reject(error);
      const backoffMs = 250 * 2 ** (cfg._retryCount - 1);
      await new Promise((r) => setTimeout(r, backoffMs));
      return _client!.request(cfg);
    },
  );
}

export function getClient(): AxiosInstance {
  if (!_client) throw new Error('API client not initialised — call initClient() first');
  return _client;
}

export function setUserId(id: string) {
  _userId = id;
  if (_client) _client.defaults.headers.common['X-User-Id'] = id;
}

export async function setApiBase(base: string) {
  await AsyncStorage.setItem('api_base', base);
  await initClient(); // rebuild with new base
}
