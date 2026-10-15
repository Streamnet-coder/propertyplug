import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, BACKEND_URL, EmailSettings } from "@/src/api";
import { Button, Card, Field, fonts, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const useEmailSettings = () => useQuery({ queryKey: ["email-settings"], queryFn: () => api<EmailSettings>("/email-settings") });

/** Verified company email used as Reply-To on every partner / weekly-update email. */
export function CompanyEmailCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useEmailSettings();
  const [email, setEmail] = useState("");
  const set = (d: EmailSettings) => queryClient.setQueryData(["email-settings"], d);

  const verify = useMutation({
    mutationFn: (e: string) => api<EmailSettings>("/email-settings", { body: { email: e, origin_url: BACKEND_URL } }),
    onSuccess: (d) => { set(d); setEmail(""); toast(`Confirmation sent to ${d.company_email}`); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({ mutationFn: () => api<EmailSettings>("/email-settings", { method: "DELETE" }), onSuccess: set });

  if (q.isLoading || !q.data) return <Card><ActivityIndicator color={colors.brand} /></Card>;
  const d = q.data;

  return (
    <Card style={{ gap: space.md }} testID="company-email-card">
      <View style={{ flexDirection: "row", gap: space.md, alignItems: "flex-start" }}>
        <View style={s.icon}><Icon name="at-sign" size={20} color={colors.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Company email</Text>
          <Text style={s.muted}>
            Updates to investors and partners show {d.company_name ? `“${d.company_name}”` : "your company"} in the email, and replies go straight to this address.
          </Text>
        </View>
      </View>
      {d.company_email ? (
        <View style={[s.status, { backgroundColor: d.verified ? colors.brandTertiary : colors.orangeTint }]} testID="company-email-status">
          <Icon name={d.verified ? "badge-check" : "clock"} size={16} color={d.verified ? colors.brand : colors.brandPrimary} />
          <Text style={[s.statusText, { color: d.verified ? colors.brand : colors.brandPrimary }]} numberOfLines={2}>
            {d.company_email} · {d.verified ? "Verified" : "Check your inbox to confirm"}
          </Text>
        </View>
      ) : (
        <Text style={s.muted}>Not set. Replies currently go to {d.account_email}.</Text>
      )}
      {d.company_email && !d.verified && (
        <Button small variant="outline" icon="refresh-cw" title="Resend confirmation" loading={verify.isPending} onPress={() => verify.mutate(d.company_email!)} testID="company-email-resend" />
      )}
      <Field label={d.company_email ? "Change address" : "Company email address"} value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" placeholder="updates@yourco.co.uk" testID="company-email-input" />
      <Button small icon="send" title="Send confirmation email" disabled={!EMAIL_RE.test(email.trim())} loading={verify.isPending} onPress={() => verify.mutate(email.trim())} testID="company-email-verify" />
      {d.company_email && <Button small variant="ghost" title="Remove company email" loading={remove.isPending} onPress={() => remove.mutate()} testID="company-email-remove" />}
      <Text style={s.hint}>Emails are delivered by {d.sender_name}&apos;s secure sender so they reach inboxes reliably.</Text>
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 18, marginTop: 2 },
  hint: { fontFamily: fonts.regular, fontSize: 11, color: c.muted },
  status: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.md, borderRadius: radius.md },
  statusText: { flex: 1, fontFamily: fonts.semibold, fontSize: 13 },
}));
