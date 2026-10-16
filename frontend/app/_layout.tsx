import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, LogBox, View } from "react-native";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { AuthProvider } from "@/src/auth";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { queryClient } from "@/src/query-client";
import { colors } from "@/src/theme";
import { ToastProvider } from "@/src/toast";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

export default function RootLayout() {
  const [loaded] = useFonts({
    "Inter-Regular": require("../assets/fonts/Inter-Regular.ttf"),
    "Inter-Medium": require("../assets/fonts/Inter-Medium.ttf"),
    "Inter-SemiBold": require("../assets/fonts/Inter-SemiBold.ttf"),
    "Inter-Bold": require("../assets/fonts/Inter-Bold.ttf"),
    "Inter-ExtraBold": require("../assets/fonts/Inter-ExtraBold.ttf"),
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
              <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surfaceSecondary } }}>
                <Stack.Screen name="index" />
                <Stack.Screen name="welcome" />
                <Stack.Screen name="auth" />
                <Stack.Screen name="(tabs)" />
                <Stack.Screen name="profile" />
                <Stack.Screen name="brrr" />
                <Stack.Screen name="item-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="contact-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="receipt-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="media-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="ai-estimate" options={{ presentation: "modal" }} />
                <Stack.Screen name="project-edit" options={{ presentation: "modal" }} />
                <Stack.Screen name="projects" />
                <Stack.Screen name="co-owners" />
                <Stack.Screen name="portfolio-map" />
                <Stack.Screen name="planning" />
                <Stack.Screen name="planning-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="trades-finder" />
                <Stack.Screen name="timeline" />
                <Stack.Screen name="milestone-form" options={{ presentation: "modal" }} />
                <Stack.Screen name="share-report" options={{ presentation: "modal" }} />
                <Stack.Screen name="branding" options={{ presentation: "modal" }} />
                <Stack.Screen name="payments" />
                <Stack.Screen name="snags" />
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
