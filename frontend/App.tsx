import React, { useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus, View, ActivityIndicator, StyleSheet, Platform, PermissionsAndroid } from 'react-native';
import * as IntentLauncher from 'expo-intent-launcher';
import { NavigationContainer } from '@react-navigation/native';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './src/api/queryClient';
import { initClient } from './src/api/client';
import { getUser, saveApiBase, getApiBase } from './src/store/auth';
import { setUserId } from './src/api/client';
import AppNavigator from './src/navigation/AppNavigator';
import { Colors } from './src/theme';
import { usePolarBle } from './src/hooks/usePolarBle';
import VIForegroundService from '@supersami/rn-foreground-service';
import { polarService } from './src/services/PolarService';
import { notificationService } from './src/services/NotificationService';

// API base URL — set EXPO_PUBLIC_API_URL at build time via eas.json env
// Falls back to Railway production URL so the dev client works without any env config
const DEV_API_BASE = (process.env as any)?.EXPO_PUBLIC_API_URL ?? 'https://api-production-8195d.up.railway.app';

// Register the foreground service headless task at module level.
// AppRegistry.registerHeadlessTask must be called before the JS bridge fully
// initialises — inside useEffect is too late on some Android builds.
if (Platform.OS === 'android') {
  VIForegroundService.register({
    config: {
      alert: false,
      onServiceErrorCallBack: () =>
        console.warn('[ZenFlow] foreground service error'),
    },
  });
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [hasUser, setHasUser] = useState(false);
  const appState = useRef(AppState.currentState);

  // Start Polar BLE as soon as a user account exists.
  // The hook is a no-op until hasUser flips to true.
  usePolarBle(hasUser);

  useEffect(() => {
    bootstrap();
  }, []);

  useEffect(() => {
    if (!hasUser) return;
    void notificationService.start();
    return () => {
      notificationService.stop();
    };
  }, [hasUser]);

  // Flush buffered beats immediately when the app returns to the foreground.
  // Beats are buffered during background (OS may delay the 60-s timer), so we
  // flush on resume to catch up scores without waiting for the next tick.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (appState.current !== 'active' && nextState === 'active') {
        polarService.flushNow().catch(() => {});
      }
      appState.current = nextState;
    });
    return () => sub.remove();
  }, []);

  async function bootstrap() {
    try {
      // Android 13+ (API 33+) requires POST_NOTIFICATIONS at runtime before
      // a foreground service notification can appear. Without this, Android
      // silently suppresses the notification and does not honour the foreground
      // service's Doze-mode protection.
      if (Platform.OS === 'android' && (Platform.Version as number) >= 33) {
        await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
        );
      }

      // Battery optimization exemption — opens the system page that puts this app
      // on the PowerManager.isIgnoringBatteryOptimizations whitelist.
      // This is a DEEPER OS-level exemption than the "allow background activity"
      // Settings toggle (which is just a ColorOS/MIUI UI layer).
      // Required so Android does not freeze the foreground service or close the
      // GATT connection when the app is sent to the background.
      // Garmin Connect and Polar Beat request this on first launch.
      if (Platform.OS === 'android') {
        try {
          await IntentLauncher.startActivityAsync(
            'android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS',
            { data: 'package:com.zenflow.verity' },
          );
        } catch {
          // User dismissed the dialog or already exempted — not fatal.
        }
      }

      // Use the URL saved in Settings if present; otherwise fall back to DEV_API_BASE.
      // This preserves any URL the user set in Settings across cold starts.
      const savedBase = await getApiBase();
      const apiBase = savedBase ?? DEV_API_BASE;
      if (!savedBase) await saveApiBase(apiBase);
      await initClient(apiBase);

      const stored = await getUser();
      if (stored?.userId) {
        setUserId(stored.userId);
        setHasUser(true);
      }
    } catch (e) {
      console.warn('Bootstrap error:', e);
    } finally {
      setReady(true);
    }
  }

  if (!ready) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color="#0A84FF" size="large" />
      </View>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <NavigationContainer theme={NAV_THEME}>
        <AppNavigator initialRouteName={hasUser ? 'Main' : 'Onboarding'} />
      </NavigationContainer>
    </QueryClientProvider>
  );
}

const NAV_THEME = {
  dark: true,
  colors: {
    primary:      Colors.readiness,
    background:   Colors.black,
    card:         Colors.surface1,
    text:         Colors.text,
    border:       Colors.border,
    notification: Colors.stress,
  },
};

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: Colors.black,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
