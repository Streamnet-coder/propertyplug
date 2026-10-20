import { Redirect, Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
import { Platform, View } from "react-native";

import { useAuth } from "@/src/auth";
import { DesktopHeader, DesktopSidebar } from "@/src/components/desktop-nav";
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

  // Desktop: Home/Budget/Team/Media live in a header Menu dropdown; project tools sit in a left sidebar.
  const tabs = (
    <Tabs
      screenListeners={{ tabPress: () => tap() }}
      tabBar={wide ? (props) => <DesktopHeader {...props} tabs={TABS} /> : undefined}
      screenOptions={{
        headerShown: false,
        tabBarPosition: wide ? "top" : "bottom",
        tabBarActiveTintColor: colors.brand,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border, ...(Platform.OS === "web" ? { height: 64 } : {}) },
        tabBarItemStyle: { alignSelf: "center" },
        tabBarLabelStyle: { fontFamily: fonts.semibold, fontSize: 11 },
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
  if (!wide) return tabs;
  return (
    <View style={{ flex: 1, flexDirection: "row" }}>
      <DesktopSidebar />
      <View style={{ flex: 1 }}>{tabs}</View>
    </View>
  );
}
