import React from 'react';
import { View } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Home, CalendarCheck, MessageCircle, Bell, BarChart3 } from 'lucide-react-native';
import { Colors } from '../theme';
import PlanDeltaBadge from '../components/PlanDeltaBadge';
import { usePlan } from '../hooks/usePlan';
import { DailyDataProvider } from '../contexts/DailyDataContext';
import type { PlanItem } from '../types';

// Screens
import HomeScreen from '../screens/HomeScreen';
import PlanScreen from '../screens/PlanScreen';
import CoachScreen from '../screens/CoachScreen';

// Onboarding
import OnboardingNavigator from './OnboardingNavigator';

// ─── Navigation type definitions ──────────────────────────────────────────────

export type RootStackParamList = {
  Onboarding: undefined;
  Main: undefined;
};

export type HomeStackParamList = {
  Home: undefined;
  MorningSummary: undefined;
  RealTimeData: undefined;
  ReadinessOverlay: { date: string };
  SessionSummary: {
    session_id: string;
    started_at: string;
    ended_at: string | null;
    duration_minutes: number | null;
    practice_type: string | null;
    session_score: number | null;
    coherence_avg: number | null;
    is_open: boolean;
  };
};

export type PlanStackParamList = {
  Plan: undefined;
  CompletedActivityDetail: { item: PlanItem };
};

export type HistoryStackParamList = {
  History: undefined;
  StressDetail: { date: string };
  RecoveryDetail: { date: string };
  Archetype: undefined;
  Journey: undefined;
  ReportCard: undefined;
  CheckIn: undefined;
  Settings: undefined;
  SessionSummary: {
    session_id: string;
    started_at: string;
    ended_at: string | null;
    duration_minutes: number | null;
    practice_type: string | null;
    session_score: number | null;
    coherence_avg: number | null;
    is_open: boolean;
  };
  BandWearSessionList: undefined;
  BandWearSessionDetail: {
    sessionId: string;
    startedAt: string;
    endedAt: string | null;
    durationMinutes: number | null;
    stressPct: number | null;
    recoveryPct: number | null;
    netBalance: number | null;
    hasSleepData: boolean;
    avgRmssdMs: number | null;
    avgHrBpm: number | null;
  };
};

/** Backward-compat alias so existing deep-link screen imports don't break. */
export type ProfileStackParamList = HistoryStackParamList;

/** Backward-compat alias for ActivityScreen (now embedded in HistoryScreen). */
export type ActivityStackParamList = {
  Activity: undefined;
  StressDetail: { date: string };
  RecoveryDetail: { date: string };
};

export type TabParamList = {
  TodayTab: undefined;
  PlanTab: undefined;
  CoachTab: undefined;
  ActivityTab: undefined;
  HistoryTab: undefined;
};

// ─── Stack navigators ─────────────────────────────────────────────────────────

const RootStack    = createNativeStackNavigator<RootStackParamList>();
const Tab          = createBottomTabNavigator<TabParamList>();
const HomeStack    = createNativeStackNavigator<HomeStackParamList>();
const PlanStack    = createNativeStackNavigator<PlanStackParamList>();
const HistoryStack = createNativeStackNavigator<HistoryStackParamList>();

function HomeStackNavigator() {
  return (
    <DailyDataProvider>
      <HomeStack.Navigator screenOptions={{ headerShown: false }}>
        <HomeStack.Screen name="Home"            component={HomeScreen} />
        <HomeStack.Screen
          name="MorningSummary"
          getComponent={() => require('../screens/MorningSummaryScreen').default}
        />
        <HomeStack.Screen
          name="RealTimeData"
          getComponent={() => require('../screens/RealTimeDataScreen').default}
        />
        <HomeStack.Screen
          name="ReadinessOverlay"
          getComponent={() => require('../screens/ReadinessOverlayScreen').default}
        />
        <HomeStack.Screen
          name="SessionSummary"
          getComponent={() => require('../screens/SessionSummaryScreen').default}
        />
      </HomeStack.Navigator>
    </DailyDataProvider>
  );
}

function PlanStackNavigator() {
  return (
    <PlanStack.Navigator screenOptions={{ headerShown: false }}>
      <PlanStack.Screen name="Plan"                     component={PlanScreen} />
      <PlanStack.Screen
        name="CompletedActivityDetail"
        getComponent={() => require('../screens/CompletedActivityDetailScreen').default}
      />
    </PlanStack.Navigator>
  );
}

function HistoryStackNavigator() {
  return (
    <HistoryStack.Navigator screenOptions={{ headerShown: false }}>
      <HistoryStack.Screen
        name="History"
        getComponent={() => require('../screens/HistoryScreen').default}
      />
      <HistoryStack.Screen
        name="StressDetail"
        getComponent={() => require('../screens/StressDetailScreen').default}
      />
      <HistoryStack.Screen
        name="RecoveryDetail"
        getComponent={() => require('../screens/RecoveryDetailScreen').default}
      />
      <HistoryStack.Screen
        name="Archetype"
        getComponent={() => require('../screens/ArchetypeScreen').default}
      />
      <HistoryStack.Screen
        name="Journey"
        getComponent={() => require('../screens/JourneyScreen').default}
      />
      <HistoryStack.Screen
        name="ReportCard"
        getComponent={() => require('../screens/ReportCardScreen').default}
      />
      <HistoryStack.Screen
        name="CheckIn"
        getComponent={() => require('../screens/CheckInScreen').default}
      />
      <HistoryStack.Screen
        name="Settings"
        getComponent={() => require('../screens/SettingsScreen').default}
      />
      <HistoryStack.Screen
        name="SessionSummary"
        getComponent={() => require('../screens/SessionSummaryScreen').default}
      />
      <HistoryStack.Screen
        name="BandWearSessionList"
        getComponent={() => require('../screens/BandWearSessionListScreen').default}
      />
      <HistoryStack.Screen
        name="BandWearSessionDetail"
        getComponent={() => require('../screens/BandWearSessionDetailScreen').default}
      />
    </HistoryStack.Navigator>
  );
}

// ─── Bottom tab navigator ─────────────────────────────────────────────────────

function TabNavigator() {
  const { plan } = usePlan({ pollIntervalMs: 300_000 });
  const updateCount = plan?.plan_updated_count ?? 0;

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#0A111A',
          borderTopColor: 'rgba(255,255,255,0.08)',
          borderTopWidth: 1,
          height: 80,
          paddingBottom: 16,
          paddingTop: 8,
        },
        tabBarActiveTintColor: '#FFFFFF',
        tabBarInactiveTintColor: 'rgba(255,255,255,0.55)',
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
          letterSpacing: 0.8,
          textTransform: 'uppercase',
        },
        tabBarIcon: ({ focused, color }) => {
          const iconMap: Record<string, React.ReactElement> = {
            TodayTab:   <Home size={22} color={color} />,
            PlanTab:    <CalendarCheck size={22} color={color} />,
            CoachTab:   <MessageCircle size={22} color={color} />,
            ActivityTab:<Bell size={22} color={color} />,
            HistoryTab: <BarChart3 size={22} color={color} />,
          };
          const icon = iconMap[route.name] ?? <Home size={22} color={color} />;
          return (
            <View style={{
              alignItems: 'center', justifyContent: 'center', position: 'relative',
              width: 44, height: 32, borderRadius: 16,
              backgroundColor: focused ? 'rgba(255,255,255,0.10)' : 'transparent',
            }}>
              {icon}
              {route.name === 'CoachTab' && updateCount > 0 && (
                <View style={{ position: 'absolute', top: -4, right: -8 }}>
                  <PlanDeltaBadge count={updateCount} />
                </View>
              )}
            </View>
          );
        },
      })}
    >
      <Tab.Screen name="TodayTab"   component={HomeStackNavigator}    options={{ title: 'Today'   }} />
      <Tab.Screen name="PlanTab"    component={PlanStackNavigator}    options={{ title: 'Plan'    }} />
      <Tab.Screen name="CoachTab"   component={CoachScreen}           options={{ title: 'Coach'   }} />
      <Tab.Screen
        name="ActivityTab"
        getComponent={() => require('../screens/ActivityScreen').default}
        options={{ title: 'Activity' }}
      />
      <Tab.Screen name="HistoryTab" component={HistoryStackNavigator} options={{ title: 'History' }} />
    </Tab.Navigator>
  );
}

// ─── Root navigator ───────────────────────────────────────────────────────────

interface AppNavigatorProps {
  initialRouteName?: 'Onboarding' | 'Main';
}

export default function AppNavigator({ initialRouteName = 'Onboarding' }: AppNavigatorProps) {
  return (
    <RootStack.Navigator
      initialRouteName={initialRouteName}
      screenOptions={{ headerShown: false, animation: 'fade' }}
    >
      <RootStack.Screen name="Onboarding" component={OnboardingNavigator} />
      <RootStack.Screen name="Main"       component={TabNavigator} />
    </RootStack.Navigator>
  );
}

