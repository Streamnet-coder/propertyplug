import type { BottomTabBarProps } from "expo-router/build/react-navigation/bottom-tabs";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { BrandLogo } from "@/src/components/brand";
import { fonts, Icon, IconName, ProBadge, radius, space, tap } from "@/src/components/ui";
import { useQuickActions } from "@/src/quick-actions";
import { makeStyles, useTheme } from "@/src/theme";

export type DesktopTab = { name: string; title: string; icon: IconName };

/** Desktop header (rendered as the tab bar on top): logo plus a Menu dropdown for Home, Budget, Team and Media. */
export function DesktopHeader({ state, navigation, tabs }: BottomTabBarProps & { tabs: DesktopTab[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const current = state.routes[state.index]?.name;
  const visible = tabs.filter((t) => state.routes.some((r) => r.name === t.name));
  const active = tabs.find((t) => t.name === current);
  return (
    <View style={s.header} testID="desktop-header">
      <BrandLogo />
      <View style={{ flex: 1 }} />
      <View style={{ position: "relative", zIndex: 20 }}>
        <Pressable onPress={() => { tap(); setOpen(!open); }} style={({ pressed }) => [s.menuBtn, pressed && { opacity: 0.85 }]} testID="desktop-menu-button" accessibilityRole="button" accessibilityLabel="Menu">
          <Icon name="menu" size={18} color={colors.brand} />
          <Text style={s.menuText}>{active ? active.title : "Menu"}</Text>
          <Icon name={open ? "chevron-up" : "chevron-down"} size={16} color={colors.brand} />
        </Pressable>
        {open && (
          <View style={s.dropdown} testID="desktop-menu">
            {visible.map((t) => {
              const on = t.name === current;
              return (
                <Pressable key={t.name} onPress={() => { tap(); setOpen(false); navigation.navigate(t.name as never); }}
                  style={({ pressed }) => [s.item, on && { backgroundColor: colors.brandTertiary }, pressed && { opacity: 0.85 }]} testID={`tab-${t.name === "index" ? "home" : t.name}`}>
                  <Icon name={t.icon} size={18} color={on ? colors.brand : colors.onSurfaceTertiary} />
                  <Text style={[s.itemText, on && { color: colors.brand }]}>{t.title}</Text>
                </Pressable>
              );
            })}
          </View>
        )}
      </View>
    </View>
  );
}

/** Desktop left sidebar with the project shortcuts (AI cost, BRRR, Sold prices, EPC, Share, Receipt, Snags, My tasks). */
export function DesktopSidebar() {
  const s = useStyles();
  const { colors } = useTheme();
  const { actions, isPro } = useQuickActions();
  return (
    <View style={s.sidebar} testID="desktop-sidebar">
      <ScrollView contentContainerStyle={{ padding: space.md, gap: 4 }}>
        <Text style={s.sideLabel}>Project tools</Text>
        {actions.map((a) => (
          <Pressable key={a.id} onPress={() => { tap(); a.onPress(); }} style={({ pressed, hovered }: any) => [s.sideItem, (pressed || hovered) && { backgroundColor: colors.surfaceSecondary }]} testID={`sidebar-action-${a.id}`}>
            <View style={[s.sideIcon, a.pro && { backgroundColor: colors.orangeTint }]}>
              <Icon name={a.icon} size={18} color={a.pro ? colors.brandPrimary : colors.brand} />
            </View>
            <Text style={s.sideText} numberOfLines={1}>{a.label}</Text>
            {a.pro && !isPro && <ProBadge locked />}
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: space.xl, paddingVertical: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, zIndex: 20 },
  menuBtn: { flexDirection: "row", alignItems: "center", gap: space.sm, minHeight: 44, paddingHorizontal: space.lg, borderRadius: radius.pill, backgroundColor: c.brandTertiary },
  menuText: { fontFamily: fonts.bold, fontSize: 14, color: c.brand },
  dropdown: { position: "absolute", top: 52, right: 0, width: 220, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.xs,
    shadowColor: c.onSurface, shadowOpacity: 0.12, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 8 },
  item: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.sm },
  itemText: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  sidebar: { width: 230, backgroundColor: c.surface, borderRightWidth: 1, borderRightColor: c.border },
  sideLabel: { fontFamily: fonts.semibold, fontSize: 11, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6, paddingHorizontal: space.sm, paddingVertical: space.sm },
  sideItem: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 48, paddingHorizontal: space.sm, borderRadius: radius.md },
  sideIcon: { width: 34, height: 34, borderRadius: radius.sm, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  sideText: { flex: 1, fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
}));
