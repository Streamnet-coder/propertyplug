import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { accessLabel, InviteLinks } from "@/src/components/invite-links";
import { Button, Card, Chip, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { ProjectRow, useProjects } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type CoOwner = { id: string; email: string; name: string | null; has_account: boolean; invited_at: string; role: "co_owner" | "manager"; project_ids: string[] | null; project_names: string[] | null; money_access: boolean; auto_add: boolean; shares: Record<string, number> };
type Shared = { owner_id: string; owner_name: string; owner_email: string; since: string; projects: number; role: "co_owner" | "manager"; money_access: boolean };

export default function CoOwners() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const [role, setRole] = useState<"co_owner" | "manager">("co_owner");
  const [allProjects, setAllProjects] = useState(true);
  const [autoAdd, setAutoAdd] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ id: string; role: "co_owner" | "manager"; all: boolean; pids: string[]; money: boolean; auto: boolean } | null>(null);
  const [moneyAccess, setMoneyAccess] = useState(true);
  const projects = useProjects();
  const ownProjects = (projects.data ?? []).filter((p) => !p.shared);
  const mine = useQuery({ queryKey: ["co-owners"], queryFn: () => api<CoOwner[]>("/co-owners") });
  const shared = useQuery({ queryKey: ["co-owners", "shared"], queryFn: () => api<Shared[]>("/co-owners/shared-with-me") });
  const invitePids = role === "co_owner" && allProjects ? null : picked;
  const needsPick = invitePids !== null && !picked.length;

  const invite = useMutation({
    mutationFn: () => api<CoOwner & { email_sent: boolean }>("/co-owners", { body: { email: email.trim(), role, project_ids: invitePids, money_access: role === "co_owner" || moneyAccess, auto_add: invitePids !== null && autoAdd } }),
    onSuccess: async (c) => {
      setEmail("");
      setPicked([]);
      setMoneyAccess(true);
      await queryClient.invalidateQueries({ queryKey: ["co-owners"] });
      toast(c.email_sent ? `Invite sent to ${c.email}` : `${c.email} added. The email couldn't be sent, so let them know yourself`, c.email_sent ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/co-owners/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setConfirm(null); await queryClient.invalidateQueries({ queryKey: ["co-owners"] }); queryClient.invalidateQueries({ queryKey: ["split"] }); toast("Co-owner removed"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const scope = useMutation({
    mutationFn: (v: NonNullable<typeof editing>) =>
      api<CoOwner>(`/co-owners/${v.id}`, { method: "PUT", body: { role: v.role, project_ids: v.role === "co_owner" && v.all ? null : v.pids, money_access: v.role === "co_owner" || v.money, auto_add: !(v.role === "co_owner" && v.all) && v.auto } }),
    onSuccess: async (c) => { setEditing(null); await queryClient.invalidateQueries({ queryKey: ["co-owners"] }); toast(`Access updated: ${accessLabel(c)}`); },
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
          <Text style={s.bold}>Co-owners</Text> get full access, including money, to all your projects or just the ones you pick. <Text style={s.bold}>Managers</Text> get access to the projects you pick, and you choose whether they see money. Both sign in with their own PropertyPlug account. They can&apos;t delete projects, manage your billing, or remove you. On your projects they get your plan&apos;s features.
        </Text>
      </Card>

      <Button small variant="outline" icon="history" title="See who changed what" onPress={() => router.push("/project-activity")} testID="co-owners-activity-link" />
      <Button small variant="outline" icon="pie-chart" title="Ownership across all properties" onPress={() => router.push("/ownership-portfolio")} testID="co-owners-portfolio-link" />

      <Text style={s.section}>Invite someone</Text>
      <Field label="Their email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" placeholder="partner@example.com" testID="co-owner-email-input" />
      <AccessPicker role={role} all={allProjects} pids={picked} money={moneyAccess} auto={autoAdd} projects={ownProjects} testPrefix="invite"
        onChange={(v) => { setRole(v.role); setAllProjects(v.all); setPicked(v.pids); setMoneyAccess(v.money); setAutoAdd(v.auto); }} />
      <Button icon="user-plus" title={role === "manager" ? "Make manager" : "Make co-owner"} loading={invite.isPending}
        disabled={!/^\S+@\S+\.\S+$/.test(email.trim()) || needsPick} onPress={() => invite.mutate()} testID="co-owner-invite-button" />
      <Text style={[s.muted, { textAlign: "center" }]}>or invite without an email</Text>
      <InviteLinks role={role} projectIds={invitePids} moneyAccess={moneyAccess} autoAdd={autoAdd} disabled={needsPick} />

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
                {accessLabel(c)}{c.money_access ? " · full access" : " · tasks only (no money)"}{c.auto_add ? " · auto-adds new projects" : ""}
              </Text>
            </View>
            {confirm !== c.id && (
              <Pressable onPress={() => setConfirm(c.id)} hitSlop={6} style={({ pressed }) => [s.binBtn, pressed && { opacity: 0.7 }]} accessibilityLabel={`Remove ${c.name || c.email}`} testID={`co-owner-remove-${c.id}`}>
                <Icon name="trash-2" size={20} color={colors.error} />
              </Pressable>
            )}
          </View>
          {confirm !== c.id && editing?.id !== c.id && <ShareAll c={c} projects={ownProjects} />}
          {editing?.id === c.id ? (
            <View style={{ gap: space.sm }}>
              <AccessPicker role={editing.role} all={editing.all} pids={editing.pids} money={editing.money} auto={editing.auto} projects={ownProjects} testPrefix={`edit-${c.id}`}
                onChange={(v) => setEditing({ ...editing, ...v })} />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" title="Cancel" onPress={() => setEditing(null)} style={{ flex: 1 }} testID={`co-owner-scope-cancel-${c.id}`} />
                <Button small title="Save access" disabled={!(editing.role === "co_owner" && editing.all) && !editing.pids.length} loading={scope.isPending} onPress={() => scope.mutate(editing)} style={{ flex: 1 }} testID={`co-owner-scope-save-${c.id}`} />
              </View>
            </View>
          ) : confirm !== c.id && (
            <Button small variant="ghost" icon="briefcase" title="Change access" onPress={() => setEditing({ id: c.id, role: c.role, all: c.project_ids === null, pids: c.project_ids ?? [], money: c.money_access, auto: c.auto_add })} testID={`co-owner-scope-${c.id}`} />
          )}
          {confirm === c.id && (
            <View style={{ gap: space.sm }}>
            <Text style={[s.muted, { color: colors.error }]}>Remove {c.name || c.email}? They lose access to every shared project straight away and their ownership shares are cleared.</Text>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="outline" title="Cancel" onPress={() => setConfirm(null)} style={{ flex: 1 }} testID={`co-owner-remove-cancel-${c.id}`} />
              <Button small variant="danger" title="Remove access" loading={remove.isPending} onPress={() => remove.mutate(c.id)} style={{ flex: 1 }} testID={`co-owner-remove-confirm-${c.id}`} />
            </View>
            </View>
          )}
        </Card>
      ))}

      {(shared.data ?? []).length > 0 && <Text style={s.section}>Shared with you</Text>}
      {(shared.data ?? []).length > 0 && (
        <Button small variant="secondary" icon="wallet" title="My ownership & statements" onPress={() => router.push("/my-ownership")} testID="co-owners-my-ownership-link" />
      )}
      {(shared.data ?? []).map((o) => (
        <Card key={o.owner_id} style={{ gap: space.sm }} testID={`shared-owner-${o.owner_id}`}>
          <View style={s.row}>
            <Icon name="users" size={20} color={colors.brand} />
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{o.owner_name}</Text>
              <Text style={s.muted}>{o.role === "manager" ? "Manager" : "Co-owner"}{o.money_access ? "" : " (tasks only)"} · {o.owner_email} · {o.projects} project{o.projects === 1 ? "" : "s"} · open from My projects</Text>
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

/** One % for this person on every project they can access; the owner's share shrinks to fit. */
function ShareAll({ c, projects }: { c: CoOwner; projects: ProjectRow[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [pct, setPct] = useState("");
  const scoped = c.project_ids === null ? projects : projects.filter((p) => c.project_ids!.includes(p.id));
  const vals = scoped.map((p) => c.shares[p.id] ?? 0);
  const same = vals.length > 0 && vals.every((v) => v === vals[0]);
  const summary = !vals.some((v) => v > 0) ? "No ownership share yet" : same ? `${vals[0]}% of all ${vals.length} project${vals.length === 1 ? "" : "s"}` : `Varies: ${scoped.map((p) => `${p.name} ${c.shares[p.id] ?? 0}%`).join(" · ")}`;
  const n = Number(pct);
  const apply = useMutation({
    mutationFn: () => api<{ pct: number; count: number }>(`/co-owners/${c.id}/apply-share`, { body: { pct: n } }),
    onSuccess: async (r) => {
      setPct("");
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["co-owners"] }), queryClient.invalidateQueries({ queryKey: ["split"] }), queryClient.invalidateQueries({ queryKey: ["ownership-portfolio"] })]);
      toast(`${r.pct}% applied to ${r.count} project${r.count === 1 ? "" : "s"}`);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  return (
    <View style={s.shareBox} testID={`co-owner-share-${c.id}`}>
      <Text style={s.name}>Ownership share</Text>
      <Text style={s.muted} testID={`co-owner-share-summary-${c.id}`}>{summary}</Text>
      <View style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }}>
        <View style={s.pctWrap}>
          <TextInput value={pct} onChangeText={setPct} keyboardType="decimal-pad" placeholder="25" placeholderTextColor={colors.muted} style={s.pctInput} maxLength={6} testID={`co-owner-share-input-${c.id}`} />
          <Text style={s.muted}>%</Text>
        </View>
        <Button small icon="layers" title="Apply to all their projects" style={{ flex: 1 }} disabled={pct.trim() === "" || !Number.isFinite(n) || n < 0 || n > 100}
          loading={apply.isPending} onPress={() => apply.mutate()} testID={`co-owner-share-apply-${c.id}`} />
      </View>
      <Text style={s.muted}>Your share shrinks to fit. You can still fine-tune each project from its Ownership split.</Text>
    </View>
  );
}

type Access = { role: "co_owner" | "manager"; all: boolean; pids: string[]; money: boolean; auto: boolean };

/** Role, which projects (co-owners: all or chosen; managers: chosen) and, for managers, whether they see money. */
function AccessPicker({ role, all, pids, money, auto, projects, onChange, testPrefix }: Access & { projects: ProjectRow[]; onChange: (v: Access) => void; testPrefix: string }) {
  const s = useStyles();
  const v = { role, all, pids, money, auto };
  return (
    <View style={{ gap: space.sm }}>
      <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
        <Chip label="Co-owner · full access" icon="users" selected={role === "co_owner"} onPress={() => onChange({ ...v, role: "co_owner", money: true })} testID={`${testPrefix}-role-co-owner`} />
        <Chip label="Manager · chosen projects" icon="briefcase" selected={role === "manager"} onPress={() => onChange({ ...v, role: "manager", all: false })} testID={`${testPrefix}-role-manager`} />
      </View>
      {role === "co_owner" && (
        <>
          <Text style={s.muted}>Which projects do they co-own?</Text>
          <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
            <Chip label="All projects" icon="layers" selected={all} onPress={() => onChange({ ...v, all: true })} testID={`${testPrefix}-scope-all`} />
            <Chip label="Chosen projects" icon="list-checks" selected={!all} onPress={() => onChange({ ...v, all: false })} testID={`${testPrefix}-scope-chosen`} />
          </View>
          {all && <Text style={s.muted}>Includes projects you add later.</Text>}
        </>
      )}
      {!(role === "co_owner" && all) && <ProjectPicker projects={projects} picked={pids} onChange={(p) => onChange({ ...v, pids: p })} testPrefix={`${testPrefix}-project`} label={role === "co_owner" ? "Which projects can they fully access?" : "Which projects can they manage?"} />}
      {!(role === "co_owner" && all) && (
        <Chip label={auto ? "Auto-add new projects: on" : "Auto-add new projects: off"} icon={auto ? "check" : "plus"} selected={auto} onPress={() => onChange({ ...v, auto: !auto })} testID={`${testPrefix}-auto-add`} />
      )}
      {role === "manager" && <MoneyToggle value={money} onChange={(m) => onChange({ ...v, money: m })} testPrefix={`${testPrefix}-money`} />}
    </View>
  );
}

function MoneyToggle({ value, onChange, testPrefix }: { value: boolean; onChange: (v: boolean) => void; testPrefix: string }) {
  const s = useStyles();
  return (
    <View style={{ gap: space.sm }}>
      <Text style={s.muted}>What can they see?</Text>
      <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
        <Chip label="Full access incl. money" icon="wallet" selected={value} onPress={() => onChange(true)} testID={`${testPrefix}-full`} />
        <Chip label="Day-to-day tasks only" icon="list-checks" selected={!value} onPress={() => onChange(false)} testID={`${testPrefix}-tasks`} />
      </View>
      {!value && <Text style={s.muted}>Hides budgets, receipts, quotes, payments, rent, BRRR and mortgage figures, and reports. They keep the timeline, snags, photos, documents, team and messages.</Text>}
    </View>
  );
}

function ProjectPicker({ projects, picked, onChange, testPrefix, label }: { projects: ProjectRow[]; picked: string[]; onChange: (ids: string[]) => void; testPrefix: string; label: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ gap: 2 }} testID={`${testPrefix}-picker`}>
      <Text style={s.muted}>{label}</Text>
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
  binBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.errorTint, alignItems: "center", justifyContent: "center" },
  shareBox: { gap: space.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md },
  pctWrap: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: space.sm, backgroundColor: c.surface, minHeight: 44 },
  pctInput: { width: 56, fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface, paddingVertical: space.sm },
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
