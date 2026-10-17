import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { api } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate, useRentals } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const EMPTY = { tenant_name: "", tenant_email: "", tenant_phone: "", rent: "", deposit: "", deposit_scheme: "", deposit_protected: false, receipts_auto: true, statements_auto: true, start_date: "", end_date: "", rent_day: "1", notes: "" };
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export default function TenancyForm() {
  const { id, year } = useLocalSearchParams<{ id?: string; year?: string }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data } = useRentals(Number(year) || new Date().getFullYear());
  const existing = data?.tenancies.find((t) => t.id === id);
  const [f, setF] = useState(EMPTY);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (v: string | boolean) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (existing) setF(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, k === "deposit_protected" || k === "receipts_auto" || k === "statements_auto" ? !!(existing as any)[k] : String((existing as any)[k] ?? "")])) as typeof EMPTY);
  }, [existing]);

  const done = async (msg: string) => {
    await invalidate("rentals");
    toast(msg);
    router.back();
  };
  const save = useMutation({
    mutationFn: () =>
      api(id ? `/rentals/tenancies/${id}` : "/rentals/tenancies", {
        method: id ? "PUT" : "POST",
        body: { ...f, rent: Number(f.rent), deposit: Number(f.deposit) || 0, rent_day: Number(f.rent_day) || 1, end_date: f.end_date.trim() || null, start_date: f.start_date.trim() },
      }),
    onSuccess: () => done(id ? "Tenancy updated" : "Tenancy added"),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({ mutationFn: () => api(`/rentals/tenancies/${id}`, { method: "DELETE" }), onSuccess: () => done("Tenancy removed") });

  const submit = () => {
    setError("");
    if (!f.tenant_name.trim()) return setError("Enter the tenant's name");
    if (!(Number(f.rent) > 0)) return setError("Enter the monthly rent");
    if (!DATE_RE.test(f.start_date.trim())) return setError("Enter a start date (YYYY-MM-DD)");
    if (f.end_date.trim() && !DATE_RE.test(f.end_date.trim())) return setError("Use date format YYYY-MM-DD");
    const day = Number(f.rent_day);
    if (!(day >= 1 && day <= 28)) return setError("Rent day must be between 1 and 28");
    save.mutate();
  };

  const half = { flexBasis: "45%" as const, flexGrow: 1 };
  return (
    <FormScreen
      title={id ? "Edit tenancy" : "New tenancy"}
      testID="tenancy-form-screen"
      footer={
        <>
          <Button title={id ? "Save tenancy" : "Add tenancy"} loading={save.isPending} onPress={submit} testID="tenancy-save-button" />
          {id && <Button variant="danger" icon="trash-2" title="Delete tenancy" loading={remove.isPending} onPress={() => remove.mutate()} testID="tenancy-delete-button" />}
        </>
      }
    >
      <Field label="Tenant name" value={f.tenant_name} onChangeText={set("tenant_name")} placeholder="e.g. Sarah Jones" testID="tenancy-name-input" />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.md }}>
        <View style={half}><Field label="Email" value={f.tenant_email} onChangeText={set("tenant_email")} keyboardType="email-address" autoCapitalize="none" testID="tenancy-email-input" /></View>
        <View style={half}><Field label="Phone" value={f.tenant_phone} onChangeText={set("tenant_phone")} keyboardType="phone-pad" testID="tenancy-phone-input" /></View>
        <View style={half}><Field label="Monthly rent" value={f.rent} onChangeText={set("rent")} keyboardType="decimal-pad" placeholder="950" testID="tenancy-rent-input" /></View>
        <View style={half}><Field label="Rent due day (1–28)" value={f.rent_day} onChangeText={set("rent_day")} keyboardType="number-pad" testID="tenancy-rent-day-input" /></View>
        <View style={half}><Field label="Deposit" value={f.deposit} onChangeText={set("deposit")} keyboardType="decimal-pad" placeholder="1,100" testID="tenancy-deposit-input" /></View>
        <View style={half}><Field label="Deposit scheme" value={f.deposit_scheme} onChangeText={set("deposit_scheme")} placeholder="e.g. DPS" testID="tenancy-scheme-input" /></View>
        <View style={half}><Field label="Start date" value={f.start_date} onChangeText={set("start_date")} placeholder="YYYY-MM-DD" testID="tenancy-start-input" /></View>
        <View style={half}><Field label="End date (optional)" value={f.end_date} onChangeText={set("end_date")} placeholder="YYYY-MM-DD" testID="tenancy-end-input" /></View>
      </View>
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Deposit protected in a government scheme?</Text>
        <View style={{ flexDirection: "row", gap: space.sm }}>
          <Chip label="Yes, protected" icon="shield-check" selected={f.deposit_protected} onPress={() => set("deposit_protected")(true)} testID="tenancy-protected-yes" />
          <Chip label="Not yet" icon="shield-alert" selected={!f.deposit_protected} onPress={() => set("deposit_protected")(false)} testID="tenancy-protected-no" />
        </View>
        {!f.deposit_protected && Number(f.deposit) > 0 && <Text style={{ fontFamily: fonts.medium, fontSize: 12, color: colors.warning }} testID="tenancy-protect-warning">UK deposits must be protected within 30 days of receiving them.</Text>}
      </View>
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Email a rent receipt when payments are logged?</Text>
        <View style={{ flexDirection: "row", gap: space.sm }}>
          <Chip label="Yes, auto-send" icon="mail-check" selected={f.receipts_auto} onPress={() => set("receipts_auto")(true)} testID="tenancy-receipts-on" />
          <Chip label="Off" icon="mail-x" selected={!f.receipts_auto} onPress={() => set("receipts_auto")(false)} testID="tenancy-receipts-off" />
        </View>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary, marginTop: space.sm }}>Email an annual rent statement every January?</Text>
        <View style={{ flexDirection: "row", gap: space.sm }}>
          <Chip label="Yes, each January" icon="calendar-check" selected={f.statements_auto} onPress={() => set("statements_auto")(true)} testID="tenancy-statements-on" />
          <Chip label="Off" icon="mail-x" selected={!f.statements_auto} onPress={() => set("statements_auto")(false)} testID="tenancy-statements-off" />
        </View>
        {(f.receipts_auto || f.statements_auto) && !f.tenant_email.trim() && <Text style={{ fontFamily: fonts.regular, fontSize: 12, color: colors.muted }}>Add the tenant&apos;s email to send receipts and statements.</Text>}
      </View>
      <Field label="Notes" value={f.notes} onChangeText={set("notes")} multiline placeholder="Break clause, guarantor, inventory…" testID="tenancy-notes-input" />
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="tenancy-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
