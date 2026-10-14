import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, User } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Card, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const PRO_FEATURES: { icon: IconName; text: string }[] = [
  { icon: "calculator", text: "BRRR ROI calculator with refinance & cashflow" },
  { icon: "map-pin", text: "1/4 mile sold comparables" },
  { icon: "message-circle", text: "Subcontractor portal & WhatsApp" },
  { icon: "building-2", text: "Stakeholder & solicitor link" },
];

export default function Profile() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { user, setUser, signOut, refresh } = useAuth();
  const [paying, setPaying] = useState(false);
  const [toggling, setToggling] = useState(false);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  if (!user) return null;
  const isPro = user.plan === "pro";
  const trialDays = Math.max(0, Math.ceil((new Date(user.trial_ends).getTime() - Date.now()) / 86400000));

  const togglePlan = async (v: boolean) => {
    setToggling(true);
    try {
      setUser(await api<User>("/auth/plan", { body: { plan: v ? "pro" : "basic" } }));
      invalidate("contacts", "comparables");
      toast(v ? "Pro features unlocked" : "Switched to Basic", "info");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setToggling(false);
    }
  };

  const upgrade = async () => {
    setPaying(true);
    try {
      const { url, session_id } = await api<{ url: string; session_id: string }>("/payments/checkout", { body: { origin_url: BACKEND_URL } });
      let tries = 0;
      if (poll.current) clearInterval(poll.current);
      poll.current = setInterval(async () => {
        tries += 1;
        try {
          const st = await api<{ status: string; payment_status: string }>(`/payments/status/${session_id}`);
          if (st.payment_status === "paid") {
            clearInterval(poll.current!);
            await refresh();
            invalidate("contacts", "comparables");
            setPaying(false);
            toast("Welcome to Pro! All features unlocked");
          } else if (st.status === "expired" || tries > 90) {
            clearInterval(poll.current!);
            setPaying(false);
          }
        } catch {
          /* keep polling */
        }
      }, 2500);
      await WebBrowser.openBrowserAsync(url);
    } catch (e: any) {
      toast(e.message, "error");
      setPaying(false);
    }
  };

  return (
    <View style={s.root} testID="profile-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="profile-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Profile & plan</Text>
        <View style={{ width: 44 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xl }}>
        <Card style={s.userCard}>
          <View style={s.avatar}>
            <Text style={s.avatarText}>{user.name.charAt(0).toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.name} testID="profile-name">{user.name}</Text>
            <Text style={s.muted} testID="profile-email">{user.email}</Text>
          </View>
          <View style={[s.planBadge, isPro && { backgroundColor: colors.brandPrimary }]}>
            <Text style={[s.planText, isPro && { color: colors.onBrandPrimary }]} testID="profile-plan-badge">{user.plan.toUpperCase()}</Text>
          </View>
        </Card>

        {!user.paid_pro && (
          <View style={s.pro} testID="upgrade-card">
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
              <Icon name="crown" size={22} color={colors.brandPrimary} />
              <Text style={s.proTitle}>My Builder Pro</Text>
            </View>
            <Text style={s.proSub} testID="upgrade-card-subtitle">
              {isPro ? "You're previewing Pro on your trial. Keep it forever with a one-time £19 upgrade." : "Built for BRRR investors & developers. One-time £19 upgrade."}
            </Text>
            <View style={{ gap: space.sm, marginVertical: space.md }}>
              {PRO_FEATURES.map((f) => (
                <View key={f.text} style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }}>
                  <Icon name={f.icon} size={16} color={colors.accent} />
                  <Text style={s.proFeature}>{f.text}</Text>
                </View>
              ))}
            </View>
            <Button title={paying ? "Waiting for payment…" : "Upgrade to Pro · £19"} icon="credit-card" loading={paying} onPress={upgrade} testID="upgrade-pro-button" />
            {paying && (
              <Pressable onPress={() => { if (poll.current) clearInterval(poll.current); setPaying(false); }} testID="cancel-payment-wait" style={{ alignItems: "center", paddingTop: space.sm }}>
                <Text style={[s.muted, { color: colors.onSurfaceInverse }]}>Cancel</Text>
              </Pressable>
            )}
          </View>
        )}
        {user.paid_pro && (
          <Card style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }} testID="pro-active-card">
            <Icon name="badge-check" size={22} color={colors.success} />
            <Text style={s.name}>Pro is active. Thanks for upgrading!</Text>
          </Card>
        )}

        <Card style={{ gap: space.md }}>
          <View style={s.row}>
            <View style={{ flex: 1 }}>
              <Text style={s.rowTitle}>Pro preview mode</Text>
              <Text style={s.muted}>{user.paid_pro ? "Switch between Basic & Pro views" : `Try Pro during your trial · ${trialDays} days left`}</Text>
            </View>
            <Pressable testID="plan-toggle-switch" disabled={toggling} onPress={() => { tap(); togglePlan(!isPro); }} hitSlop={8}>
              <View pointerEvents="none">
                <Switch value={isPro} disabled={toggling} trackColor={{ true: colors.brand, false: colors.borderStrong }} thumbColor={colors.surface} />
              </View>
            </Pressable>
          </View>
        </Card>

        <Card style={{ paddingVertical: space.xs }}>
          {[
            { icon: "pencil" as IconName, label: "Edit project details", onPress: () => router.push("/project-edit"), id: "edit-project" },
            { icon: "calculator" as IconName, label: "BRRR calculator", onPress: () => router.push("/brrr"), id: "brrr" },
            { icon: "sparkles" as IconName, label: "AI cost estimate", onPress: () => router.push("/ai-estimate"), id: "ai" },
          ].map((r, i) => (
            <Pressable key={r.id} testID={`profile-link-${r.id}`} onPress={() => { tap(); r.onPress(); }} style={[s.link, i > 0 && s.divider]}>
              <Icon name={r.icon} size={20} color={colors.brand} />
              <Text style={[s.rowTitle, { flex: 1 }]}>{r.label}</Text>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </Pressable>
          ))}
        </Card>

        <Button variant="danger" icon="log-out" title="Log out" onPress={async () => { await signOut(); router.replace("/welcome"); }} testID="logout-button" />
        <Text style={[s.muted, { textAlign: "center" }]}>© 2026 My Builder App Ltd · Secure UK cloud storage</Text>
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    backgroundColor: c.surface,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  userCard: { flexDirection: "row", alignItems: "center", gap: space.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 22, color: c.onBrand },
  name: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
  planBadge: { backgroundColor: c.orangeTint, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm },
  planText: { fontFamily: fonts.extrabold, fontSize: 11, color: c.brandPrimary, letterSpacing: 0.6 },
  pro: { backgroundColor: c.surfaceInverse, borderRadius: radius.lg, padding: space.lg },
  proTitle: { fontFamily: fonts.extrabold, fontSize: 20, color: c.onSurfaceInverse },
  proSub: { fontFamily: fonts.regular, fontSize: 13, color: c.onSurfaceInverse, opacity: 0.8, marginTop: space.xs },
  proFeature: { fontFamily: fonts.medium, fontSize: 14, color: c.onSurfaceInverse },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  link: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md, minHeight: 48 },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
}));
