import React from 'react';
import { View, StyleSheet } from 'react-native';

interface CoherenceRingProps {
  size?: number;
  strokeWidth?: number;
  coherenceLevel?: number; // 0 to 1
}

export default function CoherenceRing({ 
  size = 120, 
  strokeWidth = 8, 
  coherenceLevel = 0.5 
}: CoherenceRingProps) {
  // A simple mockup of a ring by using border styling
  // We blend color from a cool blue to a calm green based on coherence
  const isHigh = coherenceLevel > 0.7;
  const ringColor = isHigh ? '#4CAF50' : '#4A90E2';

  return (
    <View style={[styles.container, { width: size, height: size }]}>
      <View
        style={[
          styles.ring,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderWidth: strokeWidth,
            borderColor: '#E0E0E0',
          },
        ]}
      />
      <View
        style={[
          styles.ringActive,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderWidth: strokeWidth,
            borderColor: ringColor,
            opacity: 0.8 + (coherenceLevel * 0.2), // Adjust opacity slightly based on coherence
            transform: [{ scale: 1.02 }], // Render slightly larger or on top
          }
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  ring: {
    position: 'absolute',
  },
  ringActive: {
    position: 'absolute',
    borderTopColor: 'transparent',
    borderRightColor: 'transparent', // Simulate partial ring progress if we wanted to
  }
});
