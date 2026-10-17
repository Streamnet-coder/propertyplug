import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Card, Chip, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { ProjectRow, useProjects } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type CoOwner = { id: string; email: string; name: string | null; has_account: boolean; invited_at: string; role: "co_owner" | "manager"; project_ids: string[] | null; project_names: string[] | null };
type Shared = { owner_id: string; owner_name: string; owner_email: string; since: string; projects: number; role: "co_owner" | "manager" };

export default function CoOwners() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const [role, setRole] = useState<"co_owner" | "manager">("co_owner");
  const [picked, setPicked] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ id: string; pids: string[] } | null>(null);
  const projects = useProjects();
  const ownProjects = (projects.data ?? []).filter((p) => !p.shared);
  const mine = useQuery({ queryKey: ["co-owners"], queryFn: () => api<CoOwner[]>("/co-owners") });
  const shared = useQuery({ queryKey: ["co-owners", "shared"], queryFn: () => api<Shared[]>("/co-owners/shared-with-me") });

  const invite = useMutation({
    mutationFn: () => api<CoOwner & { email_sent: boolean }>("/co-owners", { body: { email: email.trim(), project_ids: role === "manager" ? picked : null } }),
    onSuccess: async (c) => {
      setEmail("");
      setPicked([]);
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
  const scope = useMutation({
    mutationFn: (v: { id: string; pids: string[] | null }) => api<CoOwner>(`/co-owners/${v.id}`, { method: "PUT", body: { project_ids: v.pids } }),
    onSuccess: async (c) => { setEditing(null); await queryClient.invalidateQueries({ queryKey: ["co-owners"] }); toast(c.role === "manager" ? "Projects updated" : "Now a co-owner of all projects"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const leave = useMutation({
    mutationFn: (ownerId: string) => api(`/co-owners/shared/${ownerId}`, { method: "DELETE" }),
    onSuccess: async () => { setConfirm(null); await queryClient.invalidateQueries(); await refresh(); toast("You've left those projects"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <FormScreen title="Co-owners & managers" testID="co-owners-screen">
      <Card style={{ gap: space.sm }}>
        <Text style={s.title}>Share responsibility</Text>
        <Text style={s.muted}>
          <Text style={s.bold}>Co-owners</Text> get full access to all your current and future projects. <Text style={s.bold}>Managers</Text> get the same full access, but only to the projects you pick. Both sign in with their own PropertyPlug account and can edit everything: budgets, snags, quotes, documents, tenancies and more. They can&apos;t delete projects, manage your billing, or remove you. On your projects they get your plan&apos;s features.
        </Text>
      </Card>

      <Button small variant="outline" icon="history" title="See who changed what" onPress={() => router.push("/project-activity")} testID="co-owners-activity-link" />

      <Text style={s.section}>Invite someone</Text>
      <Field label="Their email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" placeholder="partner@example.com" testID="co-owner-email-input" />
      <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
        <Chip label="Co-owner · all projects" icon="users" selected={role === "co_owner"} onPress={() => setRole("co_owner")} testID="invite-role-co-owner" />
        <Chip label="Manager · chosen projects" icon="briefcase" selected={role === "manager"} onPress={() => setRole("manager")} testID="invite-role-manager" />
      </View>
      {role === "manager" && <ProjectPicker projects={ownProjects} picked={picked} onChange={setPicked} testPrefix="invite-project" />}
      <Button icon="user-plus" title={role === "manager" ? "Make manager" : "Make co-owner"} loading={invite.isPending}
        disabled={!/^\S+@\S+\.\S+$/.test(email.trim()) || (role === "manager" && !picked.length)} onPress={() => invite.mutate()} testID="co-owner-invite-button" />

      <Text style={s.section}>People with access ({mine.data?.length ?? 0})</Text>
      {mine.isLoading ? <ActivityIndicator color={colors.brand} /> : !mine.data?.length ? <Text style={s.muted} testID="co-owners-empty">Nobody yet.</Text> : null}
      {(mine.data ?? []).map((c) => (
        <Card key={c.id} style={{ gap: space.sm }} testID={`co-owner-${c.id}`}>
          <View style={s.row}>
            <View style={s.avatar}><Text style={s.avatarText}>{(c.name || c.email).charAt(0).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{c.name || c.email}</Text>
              <Text style={s.muted}>{c.name ? `${c.email} · ` : ""}{c.has_account ? "Has access now" : "Invited · waiting for them to sign up"}</Text>
              <Text style={[s.muted, { color: colors.brand, fontFamily: fonts.semibold }]} testID={`co-owner-role-${c.id}`}>
                {c.role === "manager" ? `Manager · ${(c.project_names ?? []).join(", ")}` : "Co-owner · all projects"}
              </Text>
            </View>
            {confirm !== c.id && (
              <Pressable onPress={() => setConfirm(c.id)} hitSlop={8} testID={`co-owner-remove-${c.id}`}><Text style={[s.muted, { color: colors.error }]}>Remove</Text></Pressable>
            )}
          </View>
          {editing?.id === c.id ? (
            <View style={{ gap: space.sm }}>
              <ProjectPicker projects={ownProjects} picked={editing.pids} onChange={(pids) => setEditing({ id: c.id, pids })} testPrefix={`edit-project-${c.id}`} />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" title="Cancel" onPress={() => setEditing(null)} style={{ flex: 1 }} testID={`co-owner-scope-cancel-${c.id}`} />
                <Button small title="Save projects" disabled={!editing.pids.length} loading={scope.isPending} onPress={() => scope.mutate({ id: c.id, pids: editing.pids })} style={{ flex: 1 }} testID={`co-owner-scope-save-${c.id}`} />
              </View>
              {c.role === "manager" && <Button small variant="ghost" icon="users" title="Give access to all projects (co-owner)" onPress={() => scope.mutate({ id: c.id, pids: null })} testID={`co-owner-make-full-${c.id}`} />}
            </View>
          ) : confirm !== c.id && (
            <Button small variant="ghost" icon="briefcase" title={c.role === "manager" ? "Change projects" : "Limit to chosen projects"} onPress={() => setEditing({ id: c.id, pids: c.project_ids ?? [] })} testID={`co-owner-scope-${c.id}`} />
          )}
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
              <Text style={s.muted}>{o.role === "manager" ? "Manager" : "Co-owner"} · {o.owner_email} · {o.projects} project{o.projects === 1 ? "" : "s"} · open from My projects</Text>
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

function ProjectPicker({ projects, picked, onChange, testPrefix }: { projects: ProjectRow[]; picked: string[]; onChange: (ids: string[]) => void; testPrefix: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ gap: 2 }} testID={`${testPrefix}-picker`}>
      <Text style={s.muted}>Which projects can they manage?</Text>
      {projects.map((p) => {
        const on = picked.includes(p.id);
        return (
          <Pressable key={p.id} onPress={() => onChange(on ? picked.filter((x) => x !== p.id) : [...picked, p.id])} style={s.pick}
            accessibilityRole="checkbox" accessibilityState={{ checked: on }} testID={`${testPrefix}-${p.id}`}>
            <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>{on && <Icon name="check" size={14} color={colors.onBrand} />}</View>
            <View style={{ flex: 1 }}>
              <Text style={s.name} numberOfLines={1}>{p.name}</Text>
              {p.address ? <Text style={s.muted} numberOfLines={1}>{p.address}</Text> : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  pick: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 48, paddingVertical: space.xs },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: c.border, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface, marginTop: space.sm },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 19 },
  bold: { fontFamily: fonts.bold, color: c.onSurface },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  avatar: { width: 36, height: 36, borderRadius: radius.pill, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 15, color: c.brand },
}));
