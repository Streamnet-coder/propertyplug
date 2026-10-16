import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, User } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Card, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { invalidate, useReferrals } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const PRO_FEATURES: { icon: IconName; text: string }[] = [
  { icon: "calculator", text: "BRRR ROI calculator with refinance & cashflow" },
  { icon: "map-pin", text: "1/4 mile sold comparables" },
  { icon: "message-circle", text: "Subcontractor portal & WhatsApp" },
  { icon: "building-2", text: "Stakeholder & solicitor link" },
];

const TIERS = [
  { id: "monthly", label: "Monthly", price: "£19.99", per: "per month", badge: "" },
  { id: "yearly", label: "Yearly", price: "£199", per: "per year", badge: "Save 17%" },
  { id: "lifetime", label: "Lifetime", price: "£499", per: "one-off", badge: "Best value" },
] as const;

export default function Profile() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { user, setUser, signOut, refresh } = useAuth();
  const referrals = useReferrals();
  const [paying, setPaying] = useState(false);
  const [tier, setTier] = useState<(typeof TIERS)[number]["id"]>("yearly");
  const [renewBusy, setRenewBusy] = useState(false);
  const [toggling, setToggling] = useState(false);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  if (!user) return null;
  const isPro = user.own_plan === "pro";
  const lifetime = user.pro_tier === "lifetime" && isPro;
  const paidActive = isPro && !!user.pro_tier;
  const trialDays = Math.max(0, Math.ceil((new Date(user.trial_ends).getTime() - Date.now()) / 86400000));

  const tiers = user.has_subscription ? TIERS.filter((t) => t.id === "lifetime") : TIERS;
  const chosen = user.has_subscription ? "lifetime" : tier; // subscribers can only add lifetime
  const setAutoRenew = async (on: boolean) => {
    setRenewBusy(true);
    try {
      await api(`/payments/subscription/${on ? "resume" : "cancel"}`, { method: "POST" });
      await refresh();
      toast(on ? "Auto-renew is back on" : "Auto-renew cancelled. Pro stays until the end of this period", "info");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setRenewBusy(false);
    }
  };

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
      const { url, session_id } = await api<{ url: string; session_id: string }>("/payments/checkout", { body: { origin_url: BACKEND_URL, tier: chosen } });
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
            <Text style={[s.planText, isPro && { color: colors.onBrandPrimary }]} testID="profile-plan-badge">{user.own_plan.toUpperCase()}</Text>
          </View>
        </Card>

        {user.acting_as && (
          <Card style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }} testID="co-owner-plan-note">
            <Icon name="users" size={20} color={colors.brand} />
            <Text style={[s.muted, { flex: 1 }]}>You&apos;re working in {user.acting_as.owner_name}&apos;s projects as a co-owner. Features there follow their plan ({user.plan === "pro" ? "Pro" : "Basic"}). Your own billing is below.</Text>
          </Card>
        )}
        {paidActive && (
          <Card style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }} testID="pro-active-card">
            <Icon name="badge-check" size={22} color={colors.success} />
            <Text style={[s.name, { flex: 1 }]}>
              {lifetime
                ? "Lifetime Pro is active. Thanks for upgrading!"
                : `Pro ${user.pro_tier} · ${user.auto_renew ? "renews" : "ends"} ${new Date(user.pro_until!).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`}
            </Text>
          </Card>
        )}
        {user.has_subscription && (
          <Card style={{ gap: space.sm }} testID="subscription-card">
            <Text style={s.rowTitle}>{user.auto_renew ? "Auto-renew is on" : "Auto-renew is off"}</Text>
            <Text style={s.muted} testID="subscription-status">
              {user.sub_status === "past_due" ? "Your last renewal payment failed. Stripe will retry; update your card from the Stripe receipt email." : user.auto_renew ? "Your card is charged automatically each period. Cancel any time and keep Pro until the period ends." : "Pro stays active until the date above, then switches to Basic."}
            </Text>
            <Button small variant={user.auto_renew ? "outline" : "primary"} title={user.auto_renew ? "Cancel auto-renew" : "Turn auto-renew back on"} loading={renewBusy} onPress={() => setAutoRenew(!user.auto_renew)} testID={user.auto_renew ? "cancel-auto-renew-button" : "resume-auto-renew-button"} />
          </Card>
        )}
        {!lifetime && (
          <View style={s.pro} testID="upgrade-card">
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
              <Icon name="crown" size={22} color={colors.brandPrimary} />
              <Text style={s.proTitle}>{paidActive ? "Extend or go lifetime" : "Builder Assist Pro"}</Text>
            </View>
            <Text style={s.proSub} testID="upgrade-card-subtitle">Built for BRRR investors & developers. Co-owners on your projects get Pro too.</Text>
            <View style={{ gap: space.sm, marginVertical: space.md }}>
              {PRO_FEATURES.map((f) => (
                <View key={f.text} style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }}>
                  <Icon name={f.icon} size={16} color={colors.accent} />
                  <Text style={s.proFeature}>{f.text}</Text>
                </View>
              ))}
            </View>
            <View style={{ flexDirection: "row", gap: space.sm, marginBottom: space.md }}>
              {tiers.map((t) => (
                <Pressable key={t.id} onPress={() => { tap(); setTier(t.id); }} style={[s.tier, chosen === t.id && s.tierOn]} testID={`tier-${t.id}`}>
                  {t.badge ? <Text style={s.tierBadge}>{t.badge}</Text> : null}
                  <Text style={s.tierLabel}>{t.label}</Text>
                  <Text style={s.tierPrice}>{t.price}</Text>
                  <Text style={s.tierPer}>{t.per}</Text>
                </Pressable>
              ))}
            </View>
            <Button title={paying ? "Waiting for payment…" : `Pay ${TIERS.find((t) => t.id === chosen)!.price} · ${TIERS.find((t) => t.id === chosen)!.label}`} icon="credit-card" loading={paying} onPress={upgrade} testID="upgrade-pro-button" />
            {chosen !== "lifetime" && <Text style={[s.proSub, { textAlign: "center" }]} testID="tier-renew-note">Renews automatically. Cancel any time and keep Pro until the period ends.</Text>}
            {paying && (
              <Pressable onPress={() => { if (poll.current) clearInterval(poll.current); setPaying(false); }} testID="cancel-payment-wait" style={{ alignItems: "center", paddingTop: space.sm }}>
                <Text style={[s.muted, { color: colors.onSurfaceInverse }]}>Cancel</Text>
              </Pressable>
            )}
          </View>
        )}

        <Card style={{ gap: space.md }}>
          <View style={s.row}>
            <View style={{ flex: 1 }}>
              <Text style={s.rowTitle}>Pro preview mode</Text>
              <Text style={s.muted}>{paidActive ? "Switch between Basic & Pro views" : `Try Pro during your trial · ${trialDays} days left`}</Text>
            </View>
            <Pressable testID="plan-toggle-switch" disabled={toggling} onPress={() => { tap(); togglePlan(!isPro); }} hitSlop={8}>
              <View pointerEvents="none">
                <Switch value={isPro} disabled={toggling} trackColor={{ true: colors.brand, false: colors.borderStrong }} thumbColor={colors.surface} />
              </View>
            </Pressable>
          </View>
        </Card>

        <Card style={{ gap: space.sm }} testID="referral-card">
          <View style={s.row}>
            <Icon name="gift" size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={s.rowTitle}>Referral rewards</Text>
              <Text style={s.muted}>Earn a free month for every lender or trade who signs up from your report & quote links.</Text>
            </View>
          </View>
          <View style={s.refStats}>
            <View style={{ flex: 1 }}>
              <Text style={s.muted}>Signups</Text>
              <Text style={s.refVal} testID="referral-count">{referrals.data?.count ?? 0}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.muted}>Free months earned</Text>
              <Text style={[s.refVal, { color: colors.success }]} testID="referral-months">+{referrals.data?.months_earned ?? 0}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.muted}>Free until</Text>
              <Text style={s.refVal} testID="referral-trial-ends">{new Date(user.trial_ends).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</Text>
            </View>
          </View>
          {(referrals.data?.recent ?? []).slice(0, 3).map((r, i) => (
            <Text key={i} style={s.muted} testID={`referral-recent-${i}`}>• {r.name} joined via your {r.source === "quote" ? "quote request" : "report link"} · {r.date}</Text>
          ))}
        </Card>

        <Card style={{ paddingVertical: space.xs }}>
          {[
            { icon: "folder-open" as IconName, label: "My projects", onPress: () => router.push("/projects"), id: "projects" },
            { icon: "users" as IconName, label: "Co-owners", onPress: () => router.push("/co-owners"), id: "co-owners" },
            { icon: "history" as IconName, label: "Project activity", onPress: () => router.push("/project-activity"), id: "project-activity" },
            { icon: "milestone" as IconName, label: "Milestone timeline", onPress: () => router.push("/timeline"), id: "timeline" },
            { icon: "file-text" as IconName, label: "Quote requests", onPress: () => router.push("/quotes"), id: "quotes" },
            { icon: "share-2" as IconName, label: "Share report with lenders", onPress: () => router.push("/share-report"), id: "share" },
            { icon: "building-2" as IconName, label: "Report branding", onPress: () => router.push("/branding"), id: "branding" },
            { icon: "calendar-check" as IconName, label: "Payment schedule", onPress: () => router.push("/payments"), id: "payments" },
            { icon: "list-checks" as IconName, label: "Snagging list", onPress: () => router.push("/snags"), id: "snags" },
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
        <Pressable testID="delete-account-link" onPress={() => router.push("/delete-account")} style={{ alignItems: "center", minHeight: 44, justifyContent: "center" }}>
          <Text style={[s.muted, { color: colors.error, fontFamily: fonts.semibold }]}>Delete account</Text>
        </Pressable>
        <Text style={[s.muted, { textAlign: "center" }]}>© 2026 Builder Assist Ltd · Secure UK cloud storage</Text>
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
  tier: { flex: 1, borderRadius: radius.md, borderWidth: 1.5, borderColor: c.borderStrong, padding: space.sm, alignItems: "center", gap: 2, minHeight: 92, justifyContent: "center" },
  tierOn: { borderColor: c.brandPrimary, backgroundColor: c.surface },
  tierBadge: { fontFamily: fonts.bold, fontSize: 9, color: c.brandPrimary, letterSpacing: 0.4, textTransform: "uppercase" },
  tierLabel: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted },
  tierPrice: { fontFamily: fonts.extrabold, fontSize: 18, color: c.brandPrimary },
  tierPer: { fontFamily: fonts.regular, fontSize: 11, color: c.muted },
  proSub: { fontFamily: fonts.regular, fontSize: 13, color: c.onSurfaceInverse, opacity: 0.8, marginTop: space.xs },
  proFeature: { fontFamily: fonts.medium, fontSize: 14, color: c.onSurfaceInverse },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  link: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md, minHeight: 48 },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  refStats: { flexDirection: "row", gap: space.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md },
  refVal: { fontFamily: fonts.extrabold, fontSize: 18, color: c.onSurface, marginTop: 2 },
}));
