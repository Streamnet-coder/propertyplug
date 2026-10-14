import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Contract, gbp, StagePayment } from "@/src/api";
import { Button, EmptyState, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, useContracts } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const today = () => new Date().toISOString().slice(0, 10);

export default function Payments() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useContracts();
  const [adding, setAdding] = useState<Contract | null>(null);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [due, setDue] = useState("");
  const [err, setErr] = useState("");

  const refresh = () => invalidate("contracts", "line-items", "project");

  const add = useMutation({
    mutationFn: () => api("/stage-payments", { body: { quote_id: adding!.quote_id, label, amount: Number(amount), due_date: due.trim() || null } }),
    onSuccess: () => {
      refresh();
      setAdding(null);
      toast("Payment scheduled");
    },
    onError: (e: Error) => setErr(e.message),
  });
  const setStatus = useMutation({
    mutationFn: (p: StagePayment) => api(`/stage-payments/${p.id}`, { method: "PUT", body: { status: p.status === "paid" ? "due" : "paid" } }),
    onSuccess: (_d, p) => {
      refresh();
      toast(p.status === "paid" ? "Marked as due" : "Marked as paid. Budget updated");
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/stage-payments/${id}`, { method: "DELETE" }), onSuccess: refresh });

  const openAdd = (c: Contract) => {
    const first = c.payments.length === 0;
    setAdding(c);
    setLabel(first ? "Deposit" : `Stage payment ${c.payments.length}`);
    setAmount(first ? String(Math.round(c.contract_amount * 0.25)) : String(c.unscheduled));
    setDue("");
    setErr("");
  };

  return (
    <View style={s.root} testID="payments-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="payments-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Payment schedule</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load payments.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="payments-retry-button" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          {!q.data?.length ? (
            <View style={{ gap: space.md }}>
              <EmptyState icon="calendar-check" title="No accepted quotes yet" subtitle="Accept a quote to plan its deposit and stage payments. We'll stop you scheduling more than the agreed price." testID="payments-empty" />
              <Button variant="outline" title="Go to quote requests" onPress={() => router.push("/quotes")} testID="payments-go-quotes" />
            </View>
          ) : (
            q.data.map((c) => {
              const pct = c.contract_amount ? Math.min(100, (c.paid / c.contract_amount) * 100) : 0;
              return (
                <View key={c.quote_id} style={s.card} testID={`contract-${c.quote_id}`}>
                  <Text style={s.title}>{c.title}</Text>
                  <Text style={s.muted}>{c.payee} · agreed {gbp(c.contract_amount, 2)}</Text>
                  <View style={s.track}><View style={[s.fill, { width: `${pct}%` }]} /></View>
                  <View style={s.stats}>
                    <View><Text style={s.muted}>Paid</Text><Text style={[s.val, { color: colors.success }]} testID={`contract-paid-${c.quote_id}`}>{gbp(c.paid, 2)}</Text></View>
                    <View><Text style={s.muted}>Left to pay</Text><Text style={s.val} testID={`contract-remaining-${c.quote_id}`}>{gbp(c.remaining, 2)}</Text></View>
                    <View><Text style={s.muted}>Unscheduled</Text><Text style={s.val}>{gbp(c.unscheduled, 2)}</Text></View>
                  </View>
                  {c.payments.map((p) => {
                    const overdue = p.status === "due" && !!p.due_date && p.due_date < today();
                    return (
                      <View key={p.id} style={s.payRow} testID={`payment-row-${p.id}`}>
                        <Pressable testID={`payment-toggle-${p.id}`} onPress={() => { tap(); setStatus.mutate(p); }} hitSlop={8} style={[s.check, p.status === "paid" && { backgroundColor: colors.success, borderColor: colors.success }]}>
                          {p.status === "paid" && <Icon name="check" size={14} color={colors.onSuccess} />}
                        </Pressable>
                        <View style={{ flex: 1 }}>
                          <Text style={[s.payLabel, p.status === "paid" && { color: colors.muted }]}>{p.label}</Text>
                          <Text style={[s.muted, overdue && { color: colors.error }]}>
                            {p.status === "paid" ? `Paid ${p.paid_at?.slice(0, 10)}` : p.due_date ? `${overdue ? "Overdue · " : "Due "}${p.due_date}` : "No due date"}
                          </Text>
                        </View>
                        <Text style={s.payAmt}>{gbp(p.amount, 2)}</Text>
                        <Pressable testID={`payment-delete-${p.id}`} onPress={() => remove.mutate(p.id)} hitSlop={8} style={{ padding: 4 }}>
                          <Icon name="trash-2" size={16} color={colors.muted} />
                        </Pressable>
                      </View>
                    );
                  })}
                  {c.unscheduled > 0.009 ? (
                    <Button small variant="secondary" icon="plus" title="Schedule payment" onPress={() => openAdd(c)} testID={`contract-add-payment-${c.quote_id}`} />
                  ) : (
                    <View style={s.full}><Icon name="shield-check" size={16} color={colors.success} /><Text style={[s.muted, { color: colors.success }]}>Fully scheduled. Overpayment protected</Text></View>
                  )}
                </View>
              );
            })
          )}
        </ScrollView>
      )}

      <Modal visible={!!adding} transparent animationType="fade" onRequestClose={() => setAdding(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.overlay}>
          <Pressable style={{ flex: 1 }} onPress={() => setAdding(null)} />
          <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="payment-add-modal">
            <Text style={s.title}>Schedule payment · {adding?.payee}</Text>
            <Text style={s.muted}>Up to {gbp(adding?.unscheduled ?? 0, 2)} left to schedule on this quote.</Text>
            <Field label="Label" value={label} onChangeText={setLabel} placeholder="Deposit, first fix complete…" testID="payment-label-input" />
            <View style={{ flexDirection: "row", gap: space.md }}>
              <View style={{ flex: 1 }}><Field label="Amount (£)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="payment-amount-input" /></View>
              <View style={{ flex: 1 }}><Field label="Due date" value={due} onChangeText={setDue} placeholder="YYYY-MM-DD" testID="payment-due-input" /></View>
            </View>
            {err ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="payment-add-error">{err}</Text> : null}
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button variant="outline" title="Cancel" onPress={() => setAdding(null)} style={{ flex: 1 }} testID="payment-add-cancel" />
              <Button title="Save" loading={add.isPending} onPress={() => { setErr(""); add.mutate(); }} style={{ flex: 1 }} testID="payment-add-save" />
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.sm },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  track: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden", marginTop: space.xs },
  fill: { height: 8, borderRadius: 4, backgroundColor: c.success },
  stats: { flexDirection: "row", justifyContent: "space-between", paddingVertical: space.xs },
  val: { fontFamily: fonts.extrabold, fontSize: 15, color: c.onSurface, marginTop: 2 },
  payRow: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.sm, borderTopWidth: 1, borderTopColor: c.divider },
  check: { width: 26, height: 26, borderRadius: 13, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  payLabel: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  payAmt: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  full: { flexDirection: "row", alignItems: "center", gap: 6, justifyContent: "center", minHeight: 40 },
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
}));
