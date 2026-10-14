import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Pressable, Switch, Text, View } from "react-native";

import { api, DigestSettings } from "@/src/api";
import { Button, Card, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function DigestEmailCard({ hasLink }: { hasLink: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["digest-settings"], queryFn: () => api<DigestSettings>("/digest/settings") });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const d = q.data;

  const save = useMutation({
    mutationFn: (body: Pick<DigestSettings, "recipients" | "auto">) => api<DigestSettings>("/digest/settings", { method: "PUT", body }),
    onSuccess: (r) => queryClient.setQueryData(["digest-settings"], r),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const send = useMutation({
    mutationFn: () => api<{ sent: number; failed: number }>("/digest/send-now", { method: "POST" }),
    onSuccess: (r) => { toast(`Emailed ${r.sent} partner${r.sent === 1 ? "" : "s"}${r.failed ? ` · ${r.failed} failed` : ""}`); q.refetch(); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (q.isLoading || !d) return <Card><ActivityIndicator color={colors.brand} /></Card>;
  const valid = EMAIL_RE.test(email.trim());
  const add = () => {
    if (!valid) return;
    tap();
    save.mutate({ recipients: [...d.recipients, { name: name.trim(), email: email.trim().toLowerCase() }], auto: d.auto });
    setName("");
    setEmail("");
  };

  return (
    <Card style={{ gap: space.md }} testID="digest-email-card">
      <View style={{ flexDirection: "row", gap: space.md, alignItems: "flex-start" }}>
        <View style={s.icon}><Icon name="mail" size={20} color={colors.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Email partners every Monday</Text>
          <Text style={s.muted}>We send last week&apos;s update link at 8am UK time. Replies come straight to you.</Text>
        </View>
      </View>
      <View style={s.toggleRow}>
        <Text style={s.label}>Send automatically</Text>
        <Switch
          testID="digest-auto-switch"
          value={d.auto}
          disabled={!hasLink || !d.recipients.length}
          onValueChange={(v) => save.mutate({ recipients: d.recipients, auto: v })}
          trackColor={{ true: colors.brand, false: colors.borderStrong }}
          thumbColor={colors.surface}
        />
      </View>
      {!hasLink && <Text style={s.hint} testID="digest-email-needs-link">Create the weekly update link above first.</Text>}
      {d.recipients.map((r) => (
        <View key={r.email} style={s.recip} testID={`digest-recipient-${r.email}`}>
          <View style={{ flex: 1 }}>
            <Text style={s.label}>{r.name || r.email}</Text>
            {r.name ? <Text style={s.muted}>{r.email}</Text> : null}
          </View>
          <Pressable
            testID={`digest-remove-${r.email}`}
            hitSlop={10}
            style={s.del}
            onPress={() => { const rest = d.recipients.filter((x) => x.email !== r.email); save.mutate({ recipients: rest, auto: rest.length ? d.auto : false }); }}
          >
            <Icon name="x" size={16} color={colors.muted} />
          </Pressable>
        </View>
      ))}
      {d.recipients.length < 10 && (
        <View style={{ gap: space.sm }}>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <View style={{ flex: 1 }}><Field label="Name" value={name} onChangeText={setName} placeholder="e.g. Sam (investor)" testID="digest-recipient-name" /></View>
            <View style={{ flex: 1.4 }}><Field label="Email" value={email} onChangeText={setEmail} placeholder="sam@email.com" keyboardType="email-address" autoCapitalize="none" testID="digest-recipient-email" /></View>
          </View>
          <Button small variant="secondary" icon="user-plus" title="Add recipient" disabled={!valid} loading={save.isPending} onPress={add} testID="digest-add-recipient" />
        </View>
      )}
      <Button small icon="send" title="Email this week's update now" disabled={!hasLink || !d.recipients.length} loading={send.isPending} onPress={() => send.mutate()} testID="digest-send-now" />
      {d.last_sent_at ? <Text style={s.hint} testID="digest-last-sent">Last sent {new Date(d.last_sent_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</Text> : null}
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 18, marginTop: 2 },
  hint: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  label: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  toggleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  recip: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md, borderRadius: radius.md, backgroundColor: c.surfaceSecondary },
  del: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
}));
