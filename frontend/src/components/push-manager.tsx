import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Device from "expo-device";
import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Modal, Platform, Text, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, fonts, radius, space } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

const NUDGE_KEY = "pushNudgeAt";
const WEEK = 7 * 24 * 60 * 60 * 1000;

/** Ask for permission, fetch the native device token and register it with the backend. Called on login and every app open. */
async function registerForPush(userId: string) {
  if (Platform.OS === "web" || !Device.isDevice) return;
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== "granted") return;
  const token = await Notifications.getDevicePushTokenAsync();
  await api("/register-push", { body: { user_id: userId, platform: Platform.OS, device_token: String(token.data) } });
}

const go = (router: ReturnType<typeof useRouter>, data: Record<string, unknown> | undefined) => {
  const url = (data?.deeplink || data?.action_url) as string | undefined;
  if (!url) return; // no link: the tap just opens / foregrounds the app
  if (url.startsWith("http")) Linking.openURL(url);
  else router.push(url as never);
};

/** Push tap handling (warm + cold start), registration after login, and a weekly nudge when notifications are blocked. */
export function PushManager() {
  const s = useStyles();
  const router = useRouter();
  const { user } = useAuth();
  const [nudge, setNudge] = useState(false);

  useEffect(() => {
    if (Platform.OS === "web") return;
    const tapSub = Notifications.addNotificationResponseReceivedListener((r) => go(router, r.notification.request.content.data));
    Notifications.getLastNotificationResponseAsync().then((r) => r && go(router, r.notification.request.content.data));
    return () => tapSub.remove();
  }, [router]);

  useEffect(() => {
    if (Platform.OS === "web" || !user) return;
    registerForPush(user.id).catch(() => {}); // never block the app on push problems
    (async () => {
      const { status, canAskAgain } = await Notifications.getPermissionsAsync();
      if (status !== "denied" || canAskAgain) return;
      const last = await AsyncStorage.getItem(NUDGE_KEY);
      if (last && Date.now() - Number(last) <= WEEK) return;
      setNudge(true);
    })();
  }, [user]);

  const close = async (openSettings: boolean) => {
    await AsyncStorage.setItem(NUDGE_KEY, String(Date.now()));
    setNudge(false);
    if (openSettings) Linking.openSettings();
  };

  return (
    <Modal visible={nudge} transparent animationType="fade" onRequestClose={() => close(false)}>
      <View style={s.overlay}>
        <View style={s.box} testID="push-nudge">
          <Text style={s.title}>Turn on notifications</Text>
          <Text style={s.body}>Get told straight away when a tenant reports a problem, a job is fixed or a payout is recorded.</Text>
          <Button title="Open Settings" icon="settings" onPress={() => close(true)} testID="push-nudge-settings" />
          <Button variant="outline" title="Later" onPress={() => close(false)} testID="push-nudge-later" />
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "center", padding: space.lg },
  box: { backgroundColor: c.surface, borderRadius: radius.lg, padding: space.lg, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  body: { fontFamily: fonts.regular, fontSize: 14, color: c.muted, lineHeight: 20 },
}));
