import { useMutation, useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Platform, Switch, Text, View } from "react-native";

import { api } from "@/src/api";
import { Card, fonts, FormScreen, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Prefs = { repairs: boolean; jobs: boolean; fixed: boolean; payouts: boolean; invites: boolean };
const ROWS: { k: keyof Prefs; title: string; sub: string }[] = [
  { k: "repairs", title: "Tenant repair reports", sub: "When a tenant reports a problem at one of your properties" },
  { k: "jobs", title: "Jobs assigned to me", sub: "When an owner gives you a job to deal with" },
  { k: "fixed", title: "Jobs fixed", sub: "When a trade or manager marks a job as fixed" },
  { k: "payouts", title: "Payouts to me", sub: "When a co-owner payout is recorded to you" },
  { k: "invites", title: "Invites accepted", sub: "When someone joins as your co-owner or manager" },
];

/** Each user picks which push alerts they get. */
export default function NotificationSettings() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["notification-prefs"], queryFn: () => api<Prefs>("/notification-prefs") });
  const save = useMutation({
    mutationFn: (p: Prefs) => api<Prefs>("/notification-prefs", { method: "PUT", body: p }),
    onMutate: (p) => queryClient.setQueryData(["notification-prefs"], p),
    onSuccess: () => toast("Notification settings saved"),
    onError: (e: Error) => { toast(e.message, "error"); q.refetch(); },
  });
  const p = q.data;

  return (
    <FormScreen title="Notifications" testID="notification-settings-screen">
      <Text style={s.muted}>Choose which push alerts you get on this account.{Platform.OS === "web" ? " Push alerts arrive on your phone in the installed app." : ""}</Text>
      {!p ? <ActivityIndicator color={colors.brand} /> : (
        <Card style={{ gap: space.md }}>
          {ROWS.map((r) => (
            <View key={r.k} style={s.row}>
              <View style={{ flex: 1 }}>
                <Text style={s.title}>{r.title}</Text>
                <Text style={s.muted}>{r.sub}</Text>
              </View>
              <Switch value={p[r.k]} onValueChange={(v) => save.mutate({ ...p, [r.k]: v })} trackColor={{ true: colors.brand, false: colors.border }} testID={`notif-toggle-${r.k}`} />
            </View>
          ))}
        </Card>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 52 },
  title: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
