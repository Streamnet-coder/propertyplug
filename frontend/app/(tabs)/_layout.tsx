import { Redirect, Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
import { Platform } from "react-native";

import { useAuth } from "@/src/auth";
import { useCanSeeMoney } from "@/src/money";
import { fonts, Icon, IconName, tap } from "@/src/components/ui";
import { useLayout } from "@/src/layout";
import { usesNativeTabs } from "@/src/navigation";
import { useTheme } from "@/src/theme";

const TABS: { name: string; title: string; icon: IconName; sf: string }[] = [
  { name: "index", title: "Home", icon: "house", sf: "house.fill" },
  { name: "budget", title: "Budget", icon: "wallet", sf: "sterlingsign.circle.fill" },
  { name: "team", title: "Team", icon: "users", sf: "person.3.fill" },
  { name: "media", title: "Media", icon: "image", sf: "photo.on.rectangle" },
];

export default function TabsLayout() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();
  const money = useCanSeeMoney();
  const { wide } = useLayout();
  if (!loading && !user) return <Redirect href="/welcome" />;

  if (usesNativeTabs) {
    return (
      <NativeTabs tintColor={colors.brand}>
        {TABS.filter((t) => money || t.name !== "budget").map((t) => (
          <NativeTabs.Trigger key={t.name} name={t.name}>
            <NativeTabs.Trigger.Icon sf={t.sf as any} />
            <NativeTabs.Trigger.Label>{t.title}</NativeTabs.Trigger.Label>
          </NativeTabs.Trigger>
        ))}
      </NativeTabs>
    );
  }

  return (
    <Tabs
      screenListeners={{ tabPress: () => tap() }}
      screenOptions={{
        headerShown: false,
        tabBarPosition: wide ? "left" : "bottom",
        tabBarVariant: wide ? "material" : "uikit",
        tabBarLabelPosition: wide ? "beside-icon" : "below-icon",
        tabBarActiveTintColor: colors.brand,
        tabBarActiveBackgroundColor: wide ? colors.brandTertiary : undefined,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: wide
          ? { backgroundColor: colors.surface, borderRightColor: colors.border, width: 240, maxWidth: 240, paddingTop: 24, paddingHorizontal: 8 }
          : { backgroundColor: colors.surface, borderTopColor: colors.border, ...(Platform.OS === "web" ? { height: 64 } : {}) },
        tabBarItemStyle: wide ? { borderRadius: 12, marginVertical: 2, justifyContent: "flex-start", paddingHorizontal: 12, minHeight: 48 } : { alignSelf: "center" },
        tabBarLabelStyle: { fontFamily: fonts.semibold, fontSize: wide ? 14 : 11 },
      }}
    >
      {TABS.map((t) => (
        <Tabs.Screen
          key={t.name}
          name={t.name}
          options={{
            title: t.title,
            href: !money && t.name === "budget" ? null : undefined,
            tabBarButtonTestID: `tab-${t.name === "index" ? "home" : t.name}`,
            tabBarIcon: ({ color }) => <Icon name={t.icon} size={22} color={color as string} />,
          }}
        />
      ))}
    </Tabs>
  );
}
