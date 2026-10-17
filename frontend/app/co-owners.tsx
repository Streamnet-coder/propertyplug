import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Card, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type CoOwner = { id: string; email: string; name: string | null; has_account: boolean; invited_at: string };
type Shared = { owner_id: string; owner_name: string; owner_email: string; since: string; projects: number };

export default function CoOwners() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const mine = useQuery({ queryKey: ["co-owners"], queryFn: () => api<CoOwner[]>("/co-owners") });
  const shared = useQuery({ queryKey: ["co-owners", "shared"], queryFn: () => api<Shared[]>("/co-owners/shared-with-me") });

  const invite = useMutation({
    mutationFn: () => api<CoOwner & { email_sent: boolean }>("/co-owners", { body: { email: email.trim() } }),
    onSuccess: async (c) => {
      setEmail("");
      await queryClient.invalidateQueries({ queryKey: ["co-owners"] });
      toast(c.email_sent ? `Invite sent to ${c.email}` : `${c.email} added. The email couldn't be sent, so let them know yourself`, c.email_sent ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/co-owners/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setConfirm(null); await queryClient.invalidateQueries({ queryKey: ["co-owners"] }); toast("Co-owner removed"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const leave = useMutation({
    mutationFn: (ownerId: string) => api(`/co-owners/shared/${ownerId}`, { method: "DELETE" }),
    onSuccess: async () => { setConfirm(null); await queryClient.invalidateQueries(); await refresh(); toast("You've left those projects"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <FormScreen title="Co-owners" testID="co-owners-screen">
      <Card style={{ gap: space.sm }}>
        <Text style={s.title}>Share responsibility</Text>
        <Text style={s.muted}>
          Co-owners sign in with their own PropertyPlug account and get full access to <Text style={s.bold}>all your current and future projects</Text>: budgets, snags, quotes, documents, the portal and more. They can edit everything, but they can&apos;t delete projects, manage your billing, or remove you. On your projects they get your plan&apos;s features.
        </Text>
      </Card>

      <Button small variant="outline" icon="history" title="See who changed what" onPress={() => router.push("/project-activity")} testID="co-owners-activity-link" />

      <Text style={s.section}>Invite a co-owner</Text>
      <Field label="Their email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" placeholder="partner@example.com" testID="co-owner-email-input" />
      <Button icon="user-plus" title="Make co-owner" loading={invite.isPending} disabled={!/^\S+@\S+\.\S+$/.test(email.trim())} onPress={() => invite.mutate()} testID="co-owner-invite-button" />

      <Text style={s.section}>Your co-owners ({mine.data?.length ?? 0})</Text>
      {mine.isLoading ? <ActivityIndicator color={colors.brand} /> : !mine.data?.length ? <Text style={s.muted} testID="co-owners-empty">Nobody yet.</Text> : null}
      {(mine.data ?? []).map((c) => (
        <Card key={c.id} style={{ gap: space.sm }} testID={`co-owner-${c.id}`}>
          <View style={s.row}>
            <View style={s.avatar}><Text style={s.avatarText}>{(c.name || c.email).charAt(0).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{c.name || c.email}</Text>
              <Text style={s.muted}>{c.name ? `${c.email} · ` : ""}{c.has_account ? "Has access now" : "Invited · waiting for them to sign up"}</Text>
            </View>
            {confirm !== c.id && (
              <Pressable onPress={() => setConfirm(c.id)} hitSlop={8} testID={`co-owner-remove-${c.id}`}><Text style={[s.muted, { color: colors.error }]}>Remove</Text></Pressable>
            )}
          </View>
          {confirm === c.id && (
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="outline" title="Cancel" onPress={() => setConfirm(null)} style={{ flex: 1 }} testID={`co-owner-remove-cancel-${c.id}`} />
              <Button small variant="danger" title="Remove access" loading={remove.isPending} onPress={() => remove.mutate(c.id)} style={{ flex: 1 }} testID={`co-owner-remove-confirm-${c.id}`} />
            </View>
          )}
        </Card>
      ))}

      {(shared.data ?? []).length > 0 && <Text style={s.section}>Shared with you</Text>}
      {(shared.data ?? []).map((o) => (
        <Card key={o.owner_id} style={{ gap: space.sm }} testID={`shared-owner-${o.owner_id}`}>
          <View style={s.row}>
            <Icon name="users" size={20} color={colors.brand} />
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{o.owner_name}</Text>
              <Text style={s.muted}>{o.owner_email} · {o.projects} project{o.projects === 1 ? "" : "s"} · open them from My projects</Text>
            </View>
            {confirm !== o.owner_id && (
              <Pressable onPress={() => setConfirm(o.owner_id)} hitSlop={8} testID={`shared-leave-${o.owner_id}`}><Text style={[s.muted, { color: colors.error }]}>Leave</Text></Pressable>
            )}
          </View>
          {confirm === o.owner_id && (
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="outline" title="Cancel" onPress={() => setConfirm(null)} style={{ flex: 1 }} testID={`shared-leave-cancel-${o.owner_id}`} />
              <Button small variant="danger" title="Leave projects" loading={leave.isPending} onPress={() => leave.mutate(o.owner_id)} style={{ flex: 1 }} testID={`shared-leave-confirm-${o.owner_id}`} />
            </View>
          )}
        </Card>
      ))}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface, marginTop: space.sm },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 19 },
  bold: { fontFamily: fonts.bold, color: c.onSurface },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  avatar: { width: 36, height: 36, borderRadius: radius.pill, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 15, color: c.brand },
}));
