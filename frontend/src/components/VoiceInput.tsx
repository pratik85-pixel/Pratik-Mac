import React, { useState, useRef } from 'react';
import { View, TouchableOpacity, StyleSheet, Animated, TextInput, KeyboardAvoidingView, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../theme';

interface VoiceInputProps {
  onStopRecording?: (text: string) => void;
}

export default function VoiceInput({ onStopRecording }: VoiceInputProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [text, setText] = useState('');
  const scaleAnim = useRef(new Animated.Value(1)).current;

  const handleMicPressIn = () => {
    setIsRecording(true);
    Animated.spring(scaleAnim, { toValue: 1.15, useNativeDriver: true }).start();
  };

  const handleMicPressOut = () => {
    setIsRecording(false);
    Animated.spring(scaleAnim, { toValue: 1, useNativeDriver: true }).start();
  };

  const submitText = () => {
    if (text.trim() && onStopRecording) {
      onStopRecording(text.trim());
      setText('');
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.container}
    >
      <View style={styles.inputRow}>
        <TextInput
          style={styles.textInput}
          placeholder="Message Coach…"
          placeholderTextColor="#555"
          value={text}
          onChangeText={setText}
          multiline
          returnKeyType="send"
          onSubmitEditing={submitText}
          blurOnSubmit={false}
        />
        <TouchableOpacity
          onPressIn={handleMicPressIn}
          onPressOut={handleMicPressOut}
          style={styles.iconBtn}
          activeOpacity={0.7}
        >
          <Animated.View style={{ transform: [{ scale: scaleAnim }] }}>
            <Ionicons
              name="mic"
              size={19}
              color={isRecording ? '#FF453A' : '#666'}
            />
          </Animated.View>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.sendBtn, text.trim().length > 0 && styles.sendBtnActive]}
          onPress={submitText}
          activeOpacity={0.8}
        >
          <Ionicons name="arrow-up" size={17} color="#FFF" />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    width: '100%',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: '#1E1E1E',
    backgroundColor: Colors.black,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: '#1A1A1A',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#2A2A2A',
    paddingHorizontal: 14,
    paddingVertical: 8,
    gap: 8,
  },
  textInput: {
    flex: 1,
    fontSize: 15,
    color: '#FFFFFF',
    maxHeight: 100,
    paddingTop: 3,
    paddingBottom: 3,
  },
  iconBtn: {
    width: 30,
    height: 30,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtn: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: '#333',
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtnActive: {
    backgroundColor: Colors.readiness,
  },
});
