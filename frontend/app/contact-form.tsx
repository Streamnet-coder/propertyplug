import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { api, ContactKind } from "@/src/api";
import { Button, Field, fonts, FormScreen } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const TITLES: Record<ContactKind, string> = { trade: "Add tradesperson", subcontractor: "Add subcontractor", stakeholder: "Add stakeholder" };

export default function ContactForm() {
  const { kind: k } = useLocalSearchParams<{ kind?: string }>();
  const kind = (k as ContactKind) || "trade";
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const [f, setF] = useState({ name: "", role: "", phone: "", email: "", schedule: "", cost: "" });
  const [error, setError] = useState("");
  const set = (key: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [key]: v }));

  const save = useMutation({
    mutationFn: () => api("/contacts", { body: { ...f, kind, status: kind === "trade" ? "Invited" : "" } }),
    onSuccess: async () => {
      await invalidate("contacts");
      toast("Contact added");
      router.back();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <FormScreen
      title={TITLES[kind]}
      testID="contact-form-screen"
      footer={<Button title="Save contact" loading={save.isPending} onPress={() => (f.name.trim() ? save.mutate() : setError("Please enter a name"))} testID="contact-form-save-button" />}
    >
      <Field label="Name" value={f.name} onChangeText={set("name")} placeholder="e.g. Dave Miller" testID="contact-name-input" />
      <Field label={kind === "stakeholder" ? "Role" : "Trade"} value={f.role} onChangeText={set("role")} placeholder={kind === "stakeholder" ? "Financing, Legal…" : "Electrician, Plumber…"} testID="contact-role-input" />
      <Field label="Phone / WhatsApp" value={f.phone} onChangeText={set("phone")} placeholder="+44 7700 900000" keyboardType="phone-pad" testID="contact-phone-input" />
      <Field label="Email" value={f.email} onChangeText={set("email")} placeholder="name@company.co.uk" keyboardType="email-address" autoCapitalize="none" testID="contact-email-input" />
      {kind === "subcontractor" && <Field label="Schedule / scope" value={f.schedule} onChangeText={set("schedule")} placeholder="Second fix starting Monday" multiline testID="contact-schedule-input" />}
      {kind === "stakeholder" && <Field label="Fee / cost" value={f.cost} onChangeText={set("cost")} placeholder="£1,250 fixed" testID="contact-cost-input" />}
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="contact-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
