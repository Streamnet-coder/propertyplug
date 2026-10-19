import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";

import { api, ArrearsTenancy, gbp, PaymentPlan } from "@/src/api";
import { Button, Chip, Field, fonts, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const today = () => new Date().toISOString().slice(0, 10);
const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["arrears"] }), queryClient.invalidateQueries({ queryKey: ["rentals"] })]);

/** mode "create": agree a plan for the tenancy's arrears. mode "log": record an instalment against its plan. */
export function PaymentPlanSheet({ t, mode, onClose }: { t: ArrearsTenancy | null; mode: "create" | "log"; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [weekly, setWeekly] = useState(false);
  const [amount, setAmount] = useState("");
  const [start, setStart] = useState("");
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState("");
  const plan = t?.plan;

  useEffect(() => {
    if (!t) return;
    setError("");
    setNotify(!!t.tenant_email);
    setStart(today());
    setWeekly(false);
    setAmount(mode === "log" && t.plan ? String(Math.min(t.plan.next?.amount ?? t.plan.instalment, t.plan.remaining)) : String(Math.ceil(t.owed / 6)));
  }, [t, mode]);

  const n = Number(amount);
  const count = n > 0 && t ? Math.ceil(t.owed / n) : 0;
  const create = useMutation({
    mutationFn: () => api<PaymentPlan & { emailed: string | null }>(`/rentals/tenancies/${t!.tenancy_id}/payment-plan`, { body: { instalment: n, frequency: weekly ? "weekly" : "monthly", start_date: start.trim(), notify } }),
    onSuccess: async (r) => { await refresh(); toast(r.emailed === "sent" ? "Plan agreed · schedule emailed to tenant" : r.emailed === "failed" ? "Plan agreed · email failed to send" : "Payment plan agreed"); onClose(); },
    onError: (e: Error) => setError(e.message),
  });
  const log = useMutation({
    mutationFn: () => api<PaymentPlan>(`/payment-plans/${plan!.id}/payments`, { body: { amount: n, paid_on: start.trim() } }),
    onSuccess: async (r) => { await refresh(); toast(r.status === "completed" ? "Plan complete, arrears cleared" : `Instalment logged · ${gbp(r.remaining, 2, t!.currency)} left`); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const submit = () => {
    setError("");
    if (!(n > 0)) return setError("Enter an amount");
    if (!DATE_RE.test(start.trim())) return setError("Enter a date (YYYY-MM-DD)");
    (mode === "create" ? create : log).mutate();
  };

  return (
    <Modal visible={!!t} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={s.overlay} onPress={onClose}>
          {t && (
            <Pressable style={s.sheet} onPress={() => {}} testID="payment-plan-sheet">
              <ScrollView contentContainerStyle={{ gap: space.md }} keyboardShouldPersistTaps="handled">
                <View>
                  <Text style={s.title}>{mode === "create" ? "Agree a payment plan" : "Log instalment"}</Text>
                  <Text style={s.muted}>
                    {t.tenant_name} · {mode === "create" ? `${gbp(t.owed, 2, t.currency)} overdue` : `${gbp(plan?.remaining ?? 0, 2, t.currency)} left on plan`}
                  </Text>
                </View>
                {mode === "create" ? (
                  <>
                    <View style={{ flexDirection: "row", gap: space.sm }}>
                      <Chip label="Monthly" icon="calendar" selected={!weekly} onPress={() => setWeekly(false)} testID="plan-monthly" />
                      <Chip label="Weekly" icon="calendar-days" selected={weekly} onPress={() => setWeekly(true)} testID="plan-weekly" />
                    </View>
                    <View style={{ flexDirection: "row", gap: space.md }}>
                      <View style={{ flex: 1 }}><Field label={`Instalment / ${weekly ? "week" : "month"}`} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="plan-amount-input" /></View>
                      <View style={{ flex: 1 }}><Field label="First payment" value={start} onChangeText={setStart} placeholder="YYYY-MM-DD" testID="plan-start-input" /></View>
                    </View>
                    {count > 0 && <Text style={s.muted} testID="plan-summary">{count} {weekly ? "weekly" : "monthly"} payment{count === 1 ? "" : "s"}, paid on top of normal rent. Reminders pause while it&apos;s on track and resume if an instalment is over 3 days late.</Text>}
                    {t.tenant_email ? (
                      <Chip label={`Email schedule to ${t.tenant_email}`} icon={notify ? "mail-check" : "mail-x"} selected={notify} onPress={() => setNotify(!notify)} testID="plan-notify-toggle" />
                    ) : (
                      <Text style={s.muted}>Add the tenant&apos;s email to send them the schedule.</Text>
                    )}
                  </>
                ) : (
                  <View style={{ flexDirection: "row", gap: space.md }}>
                    <View style={{ flex: 1 }}><Field label="Amount received" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="plan-log-amount-input" /></View>
                    <View style={{ flex: 1 }}><Field label="Received on" value={start} onChangeText={setStart} placeholder="YYYY-MM-DD" testID="plan-log-date-input" /></View>
                  </View>
                )}
                {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="plan-error">{error}</Text> : null}
                <Button title={mode === "create" ? "Agree plan" : "Log instalment"} icon="check" loading={create.isPending || log.isPending} onPress={submit} testID="plan-save-button" />
              </ScrollView>
            </Pressable>
          )}
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, paddingBottom: space.xxl, maxHeight: "90%" },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
}));
