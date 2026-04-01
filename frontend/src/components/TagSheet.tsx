import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Modal,
  Pressable, ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export interface TagSheetProps {
  visible?: boolean;
  onClose?: () => void;
  onSkip?: () => void;
  onSelectTag?: (tag: string) => void;
  title?: string;
  tags?: string[];
}

const DEFAULT_TAGS = ['Deep Focus', 'Creative', 'Recovery', 'Warming Up', 'Stressed', 'Flow'];

export default function TagSheet({ 
  visible = false, 
  onClose = () => {}, 
  onSelectTag, 
  title = "How are you feeling?",
  tags = DEFAULT_TAGS
}: TagSheetProps) {
  
  const handleSelect = (tag: string) => {
    if (onSelectTag) onSelectTag(tag);
    onClose();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        
        <View style={styles.sheet}>
          <View style={styles.handleContainer}>
            <View style={styles.handle} />
          </View>
          
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>Select a tag to match your current state.</Text>
          
          <ScrollView contentContainerStyle={styles.tagGrid} showsVerticalScrollIndicator={false}>
            {tags.map((tag) => (
              <TouchableOpacity
                key={tag}
                style={styles.tagItem}
                onPress={() => handleSelect(tag)}
                activeOpacity={0.7}
              >
                <Text style={styles.tagText}>{tag}</Text>
                <Ionicons name="add-circle-outline" size={18} color="#4A90E2" />
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  sheet: {
    backgroundColor: '#FFFFFF',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 12,
    paddingBottom: 40,
    paddingHorizontal: 24,
    maxHeight: '60%',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.1,
    shadowRadius: 12,
    elevation: 20,
  },
  handleContainer: {
    alignItems: 'center',
    marginBottom: 20,
  },
  handle: {
    width: 40,
    height: 5,
    backgroundColor: '#E0E0E0',
    borderRadius: 3,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#333333',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 15,
    color: '#666666',
    marginBottom: 24,
  },
  tagGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  tagItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F5F8FA',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#E8F0FA',
  },
  tagText: {
    fontSize: 15,
    color: '#4A90E2',
    fontWeight: '600',
    marginRight: 8,
  }
});
