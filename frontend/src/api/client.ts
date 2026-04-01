import axios, { AxiosInstance } from 'axios';
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

  // Attach user-id header to every request automatically
  _client.interceptors.request.use((config) => {
    if (_userId) config.headers['X-User-Id'] = _userId;
    return config;
  });
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
