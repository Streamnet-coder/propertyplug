import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";

import { api, gbp, Tenancy } from "@/src/api";
import { Button, Chip, Field, fonts, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const plusYear = (d: string | null) => {
  const base = d && d > new Date().toISOString().slice(0, 10) ? new Date(d) : new Date();
  base.setFullYear(base.getFullYear() + 1);
  return base.toISOString().slice(0, 10);
};

/** One-tap renewal: extend (or go rolling), optionally change rent from a date, and email the tenant the new terms. */
export function RenewSheet({ tenancy, onClose }: { tenancy: Tenancy | null; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [rolling, setRolling] = useState(false);
  const [end, setEnd] = useState("");
  const [changeRent, setChangeRent] = useState(false);
  const [rent, setRent] = useState("");
  const [from, setFrom] = useState("");
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!tenancy) return;
    setRolling(false);
    setEnd(plusYear(tenancy.end_date));
    setChangeRent(false);
    setRent(String(tenancy.current_rent));
    setFrom(tenancy.end_date && tenancy.end_date > new Date().toISOString().slice(0, 10) ? tenancy.end_date : new Date().toISOString().slice(0, 10));
    setNotify(!!tenancy.tenant_email);
    setError("");
  }, [tenancy]);

  const save = useMutation({
    mutationFn: () =>
      api<{ emailed: string | null }>(`/rentals/tenancies/${tenancy!.id}/renew`, {
        body: { end_date: rolling ? null : end.trim(), new_rent: changeRent ? Number(rent) : null, rent_from: changeRent ? from.trim() : null, notify },
      }),
    onSuccess: async (r) => {
      await invalidate("rentals");
      toast(r.emailed === "sent" ? "Tenancy renewed · tenant emailed" : r.emailed === "failed" ? "Renewed · email failed to send" : "Tenancy renewed");
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const submit = () => {
    setError("");
    if (!rolling && !DATE_RE.test(end.trim())) return setError("Enter the new end date (YYYY-MM-DD)");
    if (changeRent && !(Number(rent) > 0)) return setError("Enter the new monthly rent");
    if (changeRent && !DATE_RE.test(from.trim())) return setError("Enter when the new rent starts (YYYY-MM-DD)");
    save.mutate();
  };

  return (
    <Modal visible={!!tenancy} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={s.overlay} onPress={onClose}>
          {tenancy && (
            <Pressable style={s.sheet} onPress={() => {}} testID="renew-sheet">
              <ScrollView contentContainerStyle={{ gap: space.md }} keyboardShouldPersistTaps="handled">
                <View>
                  <Text style={s.title}>Renew tenancy</Text>
                  <Text style={s.muted}>{tenancy.tenant_name} · currently {tenancy.end_date ? `ends ${tenancy.end_date}` : "rolling"} · {gbp(tenancy.current_rent)}/mo</Text>
                </View>
                <View style={{ flexDirection: "row", gap: space.sm }}>
                  <Chip label="Fixed term" icon="calendar" selected={!rolling} onPress={() => setRolling(false)} testID="renew-fixed" />
                  <Chip label="Rolling (periodic)" icon="infinity" selected={rolling} onPress={() => setRolling(true)} testID="renew-rolling" />
                </View>
                {!rolling && <Field label="New end date" value={end} onChangeText={setEnd} placeholder="YYYY-MM-DD" testID="renew-end-input" />}
                <View style={{ flexDirection: "row", gap: space.sm }}>
                  <Chip label="Keep rent" selected={!changeRent} onPress={() => setChangeRent(false)} testID="renew-keep-rent" />
                  <Chip label="Change rent" icon="banknote" selected={changeRent} onPress={() => setChangeRent(true)} testID="renew-change-rent" />
                </View>
                {changeRent && (
                  <View style={{ flexDirection: "row", gap: space.md }}>
                    <View style={{ flex: 1 }}><Field label="New rent / month" value={rent} onChangeText={setRent} keyboardType="decimal-pad" testID="renew-rent-input" /></View>
                    <View style={{ flex: 1 }}><Field label="Starts from" value={from} onChangeText={setFrom} placeholder="YYYY-MM-DD" testID="renew-from-input" /></View>
                  </View>
                )}
                {tenancy.tenant_email ? (
                  <Chip label={`Email new terms to ${tenancy.tenant_email}`} icon={notify ? "mail-check" : "mail-x"} selected={notify} onPress={() => setNotify(!notify)} testID="renew-notify-toggle" />
                ) : (
                  <Text style={s.muted}>Add the tenant&apos;s email to send them the new terms.</Text>
                )}
                {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="renew-error">{error}</Text> : null}
                <Button title="Confirm renewal" icon="check" loading={save.isPending} onPress={submit} testID="renew-save-button" />
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
