import { Redirect, Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
import { Platform } from "react-native";

import { useAuth } from "@/src/auth";
import { fonts, Icon, IconName, tap } from "@/src/components/ui";
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
  if (!loading && !user) return <Redirect href="/welcome" />;

  if (usesNativeTabs) {
    return (
      <NativeTabs tintColor={colors.brand}>
        {TABS.map((t) => (
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
        tabBarActiveTintColor: colors.brand,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          ...(Platform.OS === "web" ? { height: 64 } : {}),
        },
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
            tabBarButtonTestID: `tab-${t.name === "index" ? "home" : t.name}`,
            tabBarIcon: ({ color }) => <Icon name={t.icon} size={22} color={color as string} />,
          }}
        />
      ))}
    </Tabs>
  );
}
