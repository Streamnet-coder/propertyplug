import { Lucide } from "@react-native-vector-icons/lucide";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import React from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleProp,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { makeStyles, useTheme } from "@/src/theme";

export const fonts = {
  regular: "Inter-Regular",
  medium: "Inter-Medium",
  semibold: "Inter-SemiBold",
  bold: "Inter-Bold",
  extrabold: "Inter-ExtraBold",
};
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };
export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };

export type IconName = React.ComponentProps<typeof Lucide>["name"];

export function Icon({ name, size = 20, color }: { name: IconName; size?: number; color?: string }) {
  const { colors } = useTheme();
  return <Lucide name={name} size={size} color={color ?? colors.onSurface} />;
}

export const tap = () => {
  if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
};

type BtnVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";

export function Button({
  title,
  onPress,
  variant = "primary",
  icon,
  loading,
  disabled,
  testID,
  style,
  small,
}: {
  title: string;
  onPress?: () => void;
  variant?: BtnVariant;
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
  style?: StyleProp<ViewStyle>;
  small?: boolean;
}) {
  const { colors } = useTheme();
  const s = useStyles();
  const map: Record<BtnVariant, { bg: string; fg: string; border?: string }> = {
    primary: { bg: colors.brandPrimary, fg: colors.onBrandPrimary },
    secondary: { bg: colors.brandSecondary, fg: colors.onBrandSecondary },
    outline: { bg: colors.surface, fg: colors.onSurface, border: colors.borderStrong },
    ghost: { bg: "transparent", fg: colors.brand },
    danger: { bg: colors.surface, fg: colors.error, border: colors.error },
  };
  const v = map[variant];
  return (
    <Pressable
      testID={testID}
      disabled={disabled || loading}
      onPress={() => {
        tap();
        onPress?.();
      }}
      style={({ pressed }) => [
        s.btn,
        small && s.btnSmall,
        { backgroundColor: v.bg, borderColor: v.border ?? "transparent", borderWidth: v.border ? 1 : 0 },
        pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] },
        (disabled || loading) && { opacity: 0.5 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={v.fg} />
      ) : (
        <>
          {icon && <Icon name={icon} size={small ? 16 : 18} color={v.fg} />}
          <Text style={[s.btnText, small && { fontSize: 13 }, { color: v.fg }]}>{title}</Text>
        </>
      )}
    </Pressable>
  );
}

export function Card({ children, style, testID }: { children: React.ReactNode; style?: StyleProp<ViewStyle>; testID?: string }) {
  const s = useStyles();
  return (
    <View testID={testID} style={[s.card, style]}>
      {children}
    </View>
  );
}

export function Field({ label, style, ...props }: TextInputProps & { label: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={s.fieldWrap}>
      <Text style={s.label}>{label}</Text>
      <TextInput placeholderTextColor={colors.muted} style={[s.input, props.multiline && s.inputMulti, style]} {...props} />
    </View>
  );
}

export function Chip({ label, selected, onPress, testID, icon }: { label: string; selected?: boolean; onPress?: () => void; testID?: string; icon?: IconName }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={() => {
        tap();
        onPress?.();
      }}
      style={[s.chip, selected ? { backgroundColor: colors.brand, borderColor: colors.brand } : null]}
    >
      {icon && <Icon name={icon} size={14} color={selected ? colors.onBrand : colors.muted} />}
      <Text style={[s.chipText, { color: selected ? colors.onBrand : colors.onSurfaceTertiary }]}>{label}</Text>
    </Pressable>
  );
}

export function ProBadge({ locked }: { locked?: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={s.proBadge}>
      {locked && <Icon name="lock" size={10} color={colors.brandPrimary} />}
      <Text style={s.proText}>PRO</Text>
    </View>
  );
}

export function SectionTitle({ title, action, onAction, testID }: { title: string; action?: string; onAction?: () => void; testID?: string }) {
  const s = useStyles();
  return (
    <View style={s.sectionRow}>
      <Text style={s.sectionTitle}>{title}</Text>
      {action && (
        <Pressable testID={testID} onPress={onAction} hitSlop={10}>
          <Text style={s.sectionAction}>{action}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function EmptyState({ icon, title, subtitle, testID, action, onAction }: { icon: IconName; title: string; subtitle?: string; testID?: string; action?: string; onAction?: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View testID={testID} style={s.empty}>
      <View style={s.emptyIcon}>
        <Icon name={icon} size={28} color={colors.brand} />
      </View>
      <Text style={s.emptyTitle}>{title}</Text>
      {subtitle && <Text style={s.emptySub}>{subtitle}</Text>}
      {action && onAction && <Button small title={action} icon="plus" onPress={onAction} style={{ marginTop: space.md }} testID={testID ? `${testID}-action` : undefined} />}
    </View>
  );
}

export function LockedPro({ feature, description }: { feature: string; description: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  return (
    <Card style={s.locked} testID="pro-locked-card">
      <View style={[s.emptyIcon, { backgroundColor: colors.orangeTint }]}>
        <Icon name="lock" size={26} color={colors.brandPrimary} />
      </View>
      <Text style={s.emptyTitle}>{feature} is a Pro feature</Text>
      <Text style={s.emptySub}>{description}</Text>
      <Button title="Unlock Pro" icon="crown" onPress={() => router.push("/profile")} testID="unlock-pro-button" style={{ alignSelf: "stretch", marginTop: space.lg }} />
    </Card>
  );
}

export function FormScreen({
  title,
  children,
  footer,
  testID,
}: {
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  testID?: string;
}) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const top = Platform.OS === "ios" ? space.lg : insets.top + space.sm;
  return (
    <View style={s.formRoot} testID={testID}>
      <View style={[s.formHeader, { paddingTop: top }]}>
        <Text style={s.formTitle}>{title}</Text>
        <Pressable testID="form-close-button" onPress={() => router.back()} hitSlop={10} style={s.closeBtn}>
          <Icon name="x" size={20} />
        </Pressable>
      </View>
      <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={s.formBody} keyboardShouldPersistTaps="handled">
        {children}
      </KeyboardAwareScrollView>
      {footer && <View style={[s.formFooter, { paddingBottom: insets.bottom + space.lg }]}>{footer}</View>}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  btn: {
    minHeight: 52,
    borderRadius: radius.md,
    paddingHorizontal: space.xl,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: space.sm,
  },
  btnSmall: { minHeight: 40, paddingHorizontal: space.lg },
  btnText: { fontFamily: fonts.bold, fontSize: 15, letterSpacing: 0.2 },
  card: {
    backgroundColor: c.surface,
    borderRadius: radius.lg,
    padding: space.lg,
    borderWidth: 1,
    borderColor: c.border,
    shadowColor: c.onSurface,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  fieldWrap: { gap: space.xs + 2 },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  input: {
    minHeight: 50,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceSecondary,
    paddingHorizontal: space.lg,
    fontFamily: fonts.medium,
    fontSize: 15,
    color: c.onSurface,
  },
  inputMulti: { minHeight: 110, paddingTop: space.md, textAlignVertical: "top" },
  chip: {
    height: 36,
    flexShrink: 0,
    paddingHorizontal: space.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: space.xs + 2,
  },
  chipText: { fontFamily: fonts.semibold, fontSize: 13 },
  proBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: c.orangeTint,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  proText: { fontFamily: fonts.extrabold, fontSize: 10, color: c.brandPrimary, letterSpacing: 0.5 },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: space.md },
  sectionTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  sectionAction: { fontFamily: fonts.semibold, fontSize: 14, color: c.brand },
  empty: { alignItems: "center", paddingVertical: space.xxxl, paddingHorizontal: space.xl, gap: space.sm },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: space.sm,
  },
  emptyTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface, textAlign: "center" },
  emptySub: { fontFamily: fonts.regular, fontSize: 14, color: c.muted, textAlign: "center", lineHeight: 20 },
  locked: { alignItems: "center", paddingVertical: space.xl, gap: space.xs },
  formRoot: { flex: 1, backgroundColor: c.surface },
  formHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    borderBottomWidth: 1,
    borderBottomColor: c.divider,
  },
  formTitle: { fontFamily: fonts.bold, fontSize: 20, color: c.onSurface },
  closeBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: c.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  formBody: { padding: space.lg, gap: space.lg, paddingBottom: space.xxl },
  formFooter: { paddingHorizontal: space.lg, paddingTop: space.md, borderTopWidth: 1, borderTopColor: c.divider, gap: space.sm },
}));
