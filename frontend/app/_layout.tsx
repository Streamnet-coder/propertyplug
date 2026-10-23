import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, LogBox, Platform, View } from "react-native";
import * as Notifications from "expo-notifications";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { AuthProvider } from "@/src/auth";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { CreditsPrompt } from "@/src/components/credits";
import { PushManager } from "@/src/components/push-manager";
import { queryClient } from "@/src/query-client";
import { colors } from "@/src/theme";
import { ToastProvider } from "@/src/toast";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

// Push: show notifications while the app is open (module scope, native only).
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowAlert: true, shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  });
}
// Android channel must exist before any push arrives.
if (Platform.OS === "android") {
  Notifications.setNotificationChannelAsync("default", { name: "Default", importance: Notifications.AndroidImportance.MAX, sound: "default" });
}

export default function RootLayout() {
  const [loaded] = useFonts({
    "Inter-Regular": require("../assets/fonts/Inter-Regular.ttf"),
    "Inter-Medium": require("../assets/fonts/Inter-Medium.ttf"),
    "Inter-SemiBold": require("../assets/fonts/Inter-SemiBold.ttf"),
    "Inter-Bold": require("../assets/fonts/Inter-Bold.ttf"),
    "Inter-ExtraBold": require("../assets/fonts/Inter-ExtraBold.ttf"),
    "Inter-ExtraBoldItalic": require("../assets/fonts/Inter-ExtraBoldItalic.ttf"),
    Lucide: require("@react-native-vector-icons/lucide/fonts/Lucide.ttf"),
  });

  if (!loaded) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface }}>
        <ActivityIndicator color={colors.brand} />
      </View>
    );
  }

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <KeyboardProvider>
          <AuthProvider>
            <ToastProvider>
              <StatusBar style="dark" />
              <PushManager />
              <CreditsPrompt />
              <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surfaceSecondary } }}>
                <Stack.Screen name="index" />
                <Stack.Screen name="welcome" />
                <Stack.Screen name="auth" />
                <Stack.Screen name="(tabs)" />
                <Stack.Screen name="profile" />
                <Stack.Screen name="brrr" />
                <Stack.Screen name="brrr-deals" />
                <Stack.Screen name="arrears" />
                <Stack.Screen name="sold-map" />
                <Stack.Screen name="epc" />
                <Stack.Screen name="rent-comps" />
                <Stack.Screen name="item-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="contact-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="receipt-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="media-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="ai-estimate" options={{ presentation: "modal" }} />
                <Stack.Screen name="project-edit" options={{ presentation: "modal" }} />
                <Stack.Screen name="projects" />
                <Stack.Screen name="co-owners" />
                <Stack.Screen name="project-activity" />
                <Stack.Screen name="billing" />
                <Stack.Screen name="portfolio-map" />
                <Stack.Screen name="planning" />
                <Stack.Screen name="planning-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="rentals" />
                <Stack.Screen name="rent-roll" />
                <Stack.Screen name="inbox" />
                <Stack.Screen name="join/[token]" />
                <Stack.Screen name="tenancy-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="rental-expense-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="compare" />
                <Stack.Screen name="trades-finder" />
                <Stack.Screen name="timeline" />
                <Stack.Screen name="milestone-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="share-report" options={{ presentation: "modal" }} />
                <Stack.Screen name="branding" options={{ presentation: "modal" }} />
                <Stack.Screen name="payments" />
                <Stack.Screen name="snags" />
                <Stack.Screen name="repair-history" />
                <Stack.Screen name="ai-estimates" />
                <Stack.Screen name="ai-estimate-view" />
                <Stack.Screen name="ai-estimates-compare" />
                <Stack.Screen name="notification-settings" />
                <Stack.Screen name="my-ownership" />
                <Stack.Screen name="ownership-portfolio" />
                <Stack.Screen name="snag-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="shopping" />
                <Stack.Screen name="shopping-add" options={{ presentation: "modal" }} />
                <Stack.Screen name="digest" />
                <Stack.Screen name="stakeholders" />
                <Stack.Screen name="documents" />
                <Stack.Screen name="portal-access" options={{ presentation: "modal" }} />
                <Stack.Screen name="document-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="stakeholder" />
                <Stack.Screen name="delete-account" options={{ presentation: "modal" }} />
                <Stack.Screen name="quotes/index" />
                <Stack.Screen name="quotes/new" options={{ presentation: "modal" }} />
                <Stack.Screen name="quotes/[id]" />
              </Stack>
            </ToastProvider>
          </AuthProvider>
        </KeyboardProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
