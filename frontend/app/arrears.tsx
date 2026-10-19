import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, ArrearsList, ArrearsTenancy, gbp } from "@/src/api";
import { PaymentPlanSheet } from "@/src/components/payment-plan-sheet";
import { Button, Card, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { MAX_CONTENT, useLayout } from "@/src/layout";
import { MONTHS } from "@/src/rentals";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const fmtDate = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export default function ArrearsScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const q = useQuery({ queryKey: ["arrears"], queryFn: () => api<ArrearsList>("/portfolio/arrears") });
  const d = q.data;
  const { wide } = useLayout();
  const [sheet, setSheet] = useState<{ t: ArrearsTenancy; mode: "create" | "log" } | null>(null);

  return (
    <View style={s.root} testID="arrears-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="arrears-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>Rent arrears</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError || !d ? (
        <View style={s.center}><Text style={s.muted}>Could not load arrears.</Text><Button small title="Retry" onPress={() => q.refetch()} testID="arrears-retry" /></View>
      ) : (
        <ScrollView
          contentContainerStyle={[{ padding: wide ? space.xl : space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }, wide && s.contained]}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          <View style={wide ? s.cols : s.stack}>
          <View style={wide ? s.colSide : s.stack} testID={wide ? "arrears-side-column" : undefined}>
          <Card style={{ gap: space.md }} testID="arrears-totals">
            <Text style={s.label}>Overdue rent · all properties</Text>
            <Text style={[s.big, { color: d.total > 0 ? colors.error : colors.success }]} testID="arrears-total">{gbp(d.total, 2, d.home_currency)}</Text>
            <View style={s.cells}>
              <View style={s.cell}><Text style={s.cellVal} testID="arrears-count">{d.count}</Text><Text style={s.muted}>tenanc{d.count === 1 ? "y" : "ies"} behind</Text></View>
              <View style={s.cell}><Text style={s.cellVal} testID="arrears-auto-count">{d.auto_on}/{d.count}</Text><Text style={s.muted}>auto-reminders on</Text></View>
            </View>
            <Text style={s.muted}>Automatic reminders email the tenant the day after rent is missed, then every 7 days until it&apos;s paid.</Text>
          </Card>
          </View>
          <View style={wide ? s.colMain : s.stack}>
          {d.tenancies.length === 0 ? (
            <EmptyState icon="badge-check" title="Everyone is up to date" subtitle="No tenant has overdue rent right now. Missed payments will appear here automatically." testID="arrears-empty" />
          ) : (
            d.tenancies.map((t) => <ArrearsCard key={t.tenancy_id} t={t} onPlan={(mode) => setSheet({ t, mode })} />)
          )}
          </View>
          </View>
        </ScrollView>
      )}
      <PaymentPlanSheet t={sheet?.t ?? null} mode={sheet?.mode ?? "create"} onClose={() => setSheet(null)} />
    </View>
  );
}

function ArrearsCard({ t, onPlan }: { t: ArrearsTenancy; onPlan: (mode: "create" | "log") => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const [opening, setOpening] = useState(false);
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["arrears"] }), queryClient.invalidateQueries({ queryKey: ["rentals"] })]);
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api(`/rentals/tenancies/${t.tenancy_id}/auto-reminders`, { method: "PUT", body: { enabled } }),
    onSuccess: async (_, enabled) => { await refresh(); toast(enabled ? "Automatic reminders on" : "Automatic reminders off"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remind = useMutation({
    mutationFn: () => api(`/rentals/tenancies/${t.tenancy_id}/remind-arrears`, { method: "POST" }),
    onSuccess: async () => { await refresh(); toast(`Reminder sent to ${t.tenant_name}`); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const cancel = useMutation({
    mutationFn: () => api(`/payment-plans/${t.plan!.id}`, { method: "DELETE" }),
    onSuccess: async () => { setConfirmCancel(false); await refresh(); toast("Payment plan cancelled · reminders resume"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const [confirmCancel, setConfirmCancel] = useState(false);
  const plan = t.plan;
  const open = async () => {
    tap();
    setOpening(true);
    try {
      await api(`/projects/${t.project_id}/activate`, { method: "POST" });
      await queryClient.invalidateQueries();
      router.push("/rentals");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setOpening(false);
    }
  };
  const today = new Date().toISOString().slice(0, 10);
  const severe = t.oldest_days > 30;
  return (
    <Card style={[{ gap: space.md }, severe && { borderColor: colors.error }]} testID={`arrears-card-${t.tenancy_id}`}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
        <View style={s.avatar}><Text style={s.avatarText}>{t.tenant_name.slice(0, 1).toUpperCase()}</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={s.name} numberOfLines={1}>{t.tenant_name}</Text>
          <Text style={s.muted} numberOfLines={1}>{t.project_name}{t.shared ? " · shared" : ""}</Text>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={s.owed} testID={`arrears-owed-${t.tenancy_id}`}>{gbp(t.owed, 2, t.currency)}</Text>
          <Text style={[s.muted, severe && { color: colors.error }]}>{t.oldest_days} day{t.oldest_days === 1 ? "" : "s"} late</Text>
        </View>
      </View>
      <View style={s.chips}>
        {t.months.map((m) => (
          <View key={m.month} style={s.chip} testID={`arrears-month-${t.tenancy_id}-${m.month}`}>
            <Text style={s.chipText}>{MONTHS[Number(m.month.slice(5)) - 1]} {m.month.slice(2, 4)} · {gbp(m.owed, 0, t.currency)}{m.paid > 0 ? " left" : ""}</Text>
          </View>
        ))}
      </View>
      {plan && (
        <View style={[s.planBox, !plan.on_track && { borderColor: colors.error }]} testID={`arrears-plan-${t.tenancy_id}`}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
            <Icon name="calendar-check" size={16} color={plan.on_track ? colors.success : colors.error} />
            <Text style={[s.autoTitle, { flex: 1 }]}>Payment plan · {gbp(plan.instalment, 0, t.currency)}/{plan.frequency === "weekly" ? "wk" : "mo"}</Text>
            <Text style={[s.planTag, { color: plan.on_track ? colors.success : colors.error }]} testID={`arrears-plan-status-${t.tenancy_id}`}>{plan.on_track ? "ON TRACK" : "MISSED"}</Text>
          </View>
          <View style={s.bar}><View style={[s.barFill, { width: `${Math.min(100, (plan.paid / plan.amount) * 100)}%` }]} /></View>
          <Text style={s.muted}>
            {gbp(plan.paid, 0, t.currency)} of {gbp(plan.amount, 0, t.currency)} paid
            {plan.next ? ` · next ${gbp(plan.next.amount, 0, t.currency)} ${fmtDate(plan.next.due_on)}` : ""}
            {!plan.on_track ? ` · ${gbp(plan.behind, 0, t.currency)} behind, reminders resumed` : " · reminders paused"}
          </Text>
          {t.can_manage && (
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small icon="banknote" title="Log instalment" style={{ flex: 1 }} onPress={() => onPlan("log")} testID={`arrears-plan-log-${t.tenancy_id}`} />
              <Button small variant={confirmCancel ? "danger" : "outline"} title={confirmCancel ? "Tap to confirm" : "Cancel plan"} style={{ flex: 1 }} loading={cancel.isPending}
                onPress={() => (confirmCancel ? cancel.mutate() : setConfirmCancel(true))} testID={`arrears-plan-cancel-${t.tenancy_id}`} />
            </View>
          )}
        </View>
      )}
      {t.can_manage ? (
        <>
          {!plan && <Button small variant="secondary" icon="calendar-plus" title="Agree a payment plan" onPress={() => onPlan("create")} testID={`arrears-plan-create-${t.tenancy_id}`} />}
          <View style={s.autoRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.autoTitle}>Automatic reminders</Text>
              <Text style={s.muted} testID={`arrears-auto-status-${t.tenancy_id}`}>
                {!t.tenant_email ? "Add the tenant's email to turn this on"
                  : plan?.on_track && !t.next_auto_on && t.arrears_auto ? "Paused while the payment plan is on track"
                  : t.next_auto_on ? (t.next_auto_on <= today ? "Next reminder goes out within the hour" : `Next reminder ${fmtDate(t.next_auto_on)}`)
                  : "Off · you'll need to chase manually"}
              </Text>
            </View>
            <Switch value={t.arrears_auto && !!t.tenant_email} disabled={!t.tenant_email || toggle.isPending} onValueChange={(v) => toggle.mutate(v)}
              trackColor={{ true: colors.brand, false: colors.border }} testID={`arrears-auto-toggle-${t.tenancy_id}`} />
          </View>
          {t.last_reminder_at && <Text style={s.muted} testID={`arrears-last-${t.tenancy_id}`}>Last reminder sent {fmtDate(t.last_reminder_at)}</Text>}
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small variant="outline" icon="send" title="Remind now" style={{ flex: 1 }} disabled={!t.tenant_email} loading={remind.isPending} onPress={() => remind.mutate()} testID={`arrears-remind-${t.tenancy_id}`} />
            <Button small variant="secondary" icon="key-round" title="Open rent" style={{ flex: 1 }} loading={opening} onPress={open} testID={`arrears-open-${t.tenancy_id}`} />
          </View>
        </>
      ) : (
        <Text style={s.muted}>Reminders for this shared property are managed by its owner.</Text>
      )}
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  contained: { width: "100%", maxWidth: MAX_CONTENT, alignSelf: "center" },
  stack: { gap: space.lg },
  cols: { flexDirection: "row", alignItems: "flex-start", gap: space.xl },
  colSide: { width: 400, gap: space.lg },
  colMain: { flex: 1, minWidth: 0, gap: space.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  big: { fontFamily: fonts.extrabold, fontSize: 32, letterSpacing: -0.8 },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.errorTint, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 16, color: c.error },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  owed: { fontFamily: fonts.extrabold, fontSize: 17, color: c.error },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { backgroundColor: c.errorTint, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 5 },
  chipText: { fontFamily: fonts.semibold, fontSize: 12, color: c.error },
  autoRow: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md },
  planBox: { gap: space.sm, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: space.md },
  planTag: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 0.6 },
  bar: { height: 6, borderRadius: 3, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  barFill: { height: 6, backgroundColor: c.success },
  autoTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
}));
