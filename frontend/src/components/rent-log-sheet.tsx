import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";

import { api, gbp, RentMonth, Tenancy } from "@/src/api";
import { Button, Field, fonts, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { monthLabel, RENT_STATUS, rentTone, today } from "@/src/rentals";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

/** Log (or clear) a month's rent payment for a tenancy. */
export function RentLogSheet({ tenancy, month, onClose }: { tenancy: Tenancy | null; month: RentMonth | null; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (month) {
      setAmount(String(month.paid || month.due));
      setPaidOn(month.paid_on ?? today());
      setError("");
    }
  }, [month]);

  const save = useMutation({
    mutationFn: (paid: number) => api<{ receipt?: string | null }>(`/rentals/tenancies/${tenancy!.id}/rent/${month!.month}`, { method: "PUT", body: { paid_amount: paid, paid_on: paid ? paidOn.trim() || null : null } }),
    onSuccess: async (r, paid) => {
      await invalidate("rentals");
      toast(!paid ? "Payment cleared" : r.receipt === "sent" ? "Rent logged · receipt emailed" : r.receipt === "failed" ? "Rent logged · receipt email failed" : "Rent logged");
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const submit = () => {
    const n = Number(amount);
    if (!(n > 0)) return setError("Enter the amount received");
    if (paidOn.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(paidOn.trim())) return setError("Use date format YYYY-MM-DD");
    save.mutate(n);
  };

  const remind = useMutation({
    mutationFn: () => api<{ kind: "late" | "upcoming" }>(`/rentals/tenancies/${tenancy!.id}/remind`, { body: { month: month!.month } }),
    onSuccess: async (r) => {
      await invalidate("rentals");
      toast(r.kind === "late" ? "Late rent reminder sent" : "Friendly reminder sent");
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const tone = month ? rentTone(month.status, colors) : null;
  return (
    <Modal visible={!!month} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={s.overlay} onPress={onClose}>
          {month && tenancy && (
            <Pressable style={s.sheet} onPress={() => {}} testID="rent-log-sheet">
              <View style={s.row}>
                <View style={{ flex: 1 }}>
                  <Text style={s.title}>{monthLabel(month.month)} rent</Text>
                  <Text style={s.muted}>{tenancy.tenant_name} · {gbp(month.due)} due {month.due_on}</Text>
                </View>
                <View style={[s.pill, { backgroundColor: tone!.bg }]}><Text style={[s.pillText, { color: tone!.fg }]}>{RENT_STATUS[month.status]}</Text></View>
              </View>
              <Field label="Amount received" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="rent-amount-input" />
              <Field label="Paid on" value={paidOn} onChangeText={setPaidOn} placeholder="YYYY-MM-DD" testID="rent-paid-on-input" />
              {error ? <Text style={s.error} testID="rent-log-error">{error}</Text> : null}
              <Button title="Save payment" icon="check" loading={save.isPending && save.variables !== 0} onPress={submit} testID="rent-save-button" />
              {month.status !== "paid" && (
                tenancy.tenant_email ? (
                  <View style={{ gap: 4 }}>
                    <Button variant="outline" icon="send" title={month.status === "late" || (month.status === "partial" && month.due_on < today()) ? "Send late rent reminder" : "Send friendly reminder"} loading={remind.isPending} onPress={() => { setError(""); remind.mutate(); }} testID="rent-remind-button" />
                    {month.reminded_at && <Text style={[s.muted, { textAlign: "center" }]} testID="rent-reminded-at">Last reminder sent {month.reminded_at.slice(0, 10)}</Text>}
                  </View>
                ) : (
                  <Text style={[s.muted, { textAlign: "center" }]} testID="rent-remind-no-email">Add the tenant&apos;s email to send rent reminders</Text>
                )
              )}
              {month.paid > 0 && <Button variant="danger" title="Clear payment" loading={save.isPending && save.variables === 0} onPress={() => save.mutate(0)} testID="rent-clear-button" />}
            </Pressable>
          )}
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, paddingBottom: space.xxl, gap: space.md },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.bold, fontSize: 12 },
  error: { fontFamily: fonts.medium, color: c.error },
}));
