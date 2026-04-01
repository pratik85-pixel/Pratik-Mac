import AsyncStorage from '@react-native-async-storage/async-storage';
import { setUserId } from '../api/client';

const USER_ID_KEY = 'user_id';
const USER_NAME_KEY = 'user_name';
const API_BASE_KEY = 'api_base';

export const AuthStore = {
  async saveUser(userId: string, name: string): Promise<void> {
    await AsyncStorage.multiSet([
      [USER_ID_KEY, userId],
      [USER_NAME_KEY, name],
    ]);
    setUserId(userId);
  },

  async getUser(): Promise<{ userId: string; name: string } | null> {
    const [[, userId], [, name]] = await AsyncStorage.multiGet([USER_ID_KEY, USER_NAME_KEY]);
    if (!userId) return null;
    return { userId, name: name ?? 'there' };
  },

  async getUserId(): Promise<string | null> {
    return AsyncStorage.getItem(USER_ID_KEY);
  },

  async getName(): Promise<string> {
    return (await AsyncStorage.getItem(USER_NAME_KEY)) ?? 'there';
  },

  async clear(): Promise<void> {
    await AsyncStorage.multiRemove([USER_ID_KEY, USER_NAME_KEY]);
  },

  async saveApiBase(base: string): Promise<void> {
    await AsyncStorage.setItem(API_BASE_KEY, base);
  },

  async getApiBase(): Promise<string | null> {
    return AsyncStorage.getItem(API_BASE_KEY);
  },
};

// Named exports for convenience
export const saveUser     = (userId: string, name: string) => AuthStore.saveUser(userId, name);
export const getUser      = () => AuthStore.getUser();
export const getUserId    = () => AuthStore.getUserId();
export const getName      = () => AuthStore.getName();
export const clear        = () => AuthStore.clear();
export const saveApiBase  = (base: string) => AuthStore.saveApiBase(base);
export const getApiBase   = () => AuthStore.getApiBase();
