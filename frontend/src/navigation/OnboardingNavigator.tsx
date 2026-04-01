import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import OnboardingStep1 from '../screens/onboarding/Step1Welcome';
import OnboardingStep2 from '../screens/onboarding/Step2Goal';
import OnboardingStep3 from '../screens/onboarding/Step3TypicalDay';
import OnboardingStep4 from '../screens/onboarding/Step4Movement';
import OnboardingStep5 from '../screens/onboarding/Step5Lifestyle';
import OnboardingStep6 from '../screens/onboarding/Step6Decompress';
import OnboardingStep7 from '../screens/onboarding/Step7Honest';
import OnboardingStep8 from '../screens/onboarding/Step8Name';

export type OnboardingParamList = {
  Step1Welcome: undefined;
  Step2Goal: undefined;
  Step3TypicalDay: { goal: string };
  Step4Movement: { goal: string; dayType: string };
  Step5Lifestyle: { goal: string; dayType: string; movement: string[] };
  Step6Decompress: { goal: string; dayType: string; movement: string[]; lifestyle: Record<string, string> };
  Step7Honest: { goal: string; dayType: string; movement: string[]; lifestyle: Record<string, string>; decompress: string[] };
  Step8Name: { goal: string; dayType: string; movement: string[]; lifestyle: Record<string, string>; decompress: string[] };
};

const Stack = createNativeStackNavigator<OnboardingParamList>();

export default function OnboardingNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{ headerShown: false, animation: 'slide_from_right' }}
    >
      <Stack.Screen name="Step1Welcome" component={OnboardingStep1} />
      <Stack.Screen name="Step2Goal" component={OnboardingStep2} />
      <Stack.Screen name="Step3TypicalDay" component={OnboardingStep3} />
      <Stack.Screen name="Step4Movement" component={OnboardingStep4} />
      <Stack.Screen name="Step5Lifestyle" component={OnboardingStep5} />
      <Stack.Screen name="Step6Decompress" component={OnboardingStep6} />
      <Stack.Screen name="Step7Honest" component={OnboardingStep7} />
      <Stack.Screen name="Step8Name" component={OnboardingStep8} />
    </Stack.Navigator>
  );
}
