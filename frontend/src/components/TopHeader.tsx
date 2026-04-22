import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { ZEN } from '../ui/zenflow-ui-kit';

interface TopHeaderProps {
  title: string;
  eyebrow?: string;
  subtitle?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  onLeftPress?: () => void;
  onRightPress?: () => void;
  leftLabel?: string;
  rightLabel?: string;
}

export default function TopHeader({
  title,
  eyebrow,
  subtitle,
  leftIcon,
  rightIcon,
  onLeftPress,
  onRightPress,
  leftLabel,
  rightLabel,
}: TopHeaderProps) {
  return (
    <View style={s.row}>
      {/* Left icon button */}
      <TouchableOpacity
        style={s.iconBtn}
        onPress={onLeftPress}
        activeOpacity={0.8}
        disabled={!onLeftPress}
        accessibilityRole={onLeftPress ? 'button' : 'none'}
        accessibilityLabel={leftLabel}
      >
        {leftIcon ?? <View style={s.placeholder} />}
      </TouchableOpacity>

      {/* Center */}
      <View
        style={s.center}
        accessibilityRole="header"
        accessibilityLabel={eyebrow ? `${eyebrow}. ${title}${subtitle ? `. ${subtitle}` : ''}` : title}
      >
        {eyebrow ? (
          <Text style={s.eyebrow}>{eyebrow}</Text>
        ) : null}
        <Text style={s.title} numberOfLines={1}>{title}</Text>
        {subtitle ? (
          <Text style={s.subtitle}>{subtitle}</Text>
        ) : null}
      </View>

      {/* Right icon button */}
      <TouchableOpacity
        style={s.iconBtn}
        onPress={onRightPress}
        activeOpacity={0.8}
        disabled={!onRightPress}
        accessibilityRole={onRightPress ? 'button' : 'none'}
        accessibilityLabel={rightLabel}
      >
        {rightIcon ?? <View style={s.placeholder} />}
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
    marginBottom: 16,
    minHeight: 44,
  },
  iconBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  placeholder: {
    width: 40,
    height: 40,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    paddingHorizontal: 8,
  },
  eyebrow: {
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 3,
    color: ZEN.colors.textMuted,
    marginBottom: 2,
  },
  title: {
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: -0.3,
    color: ZEN.colors.white,
  },
  subtitle: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
    marginTop: 2,
    letterSpacing: 0.3,
  },
});
