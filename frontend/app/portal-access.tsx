import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { ActivityIndicator, Pressable, Switch, Text, View } from "react-native";

import { api, BACKEND_URL, DocItem, PortalMember } from "@/src/api";
import { Button, Card, Chip, Field, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { ActivityPanel, QuestionsPanel, usePortalQuestions } from "@/src/components/portal-panels";
import { AccessEndPicker, fmtEnd } from "@/src/components/access-end-picker";
import { ExpiringAccessCard } from "@/src/components/expiring-access-card";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ROLES = ["Investor", "Lender", "Business partner", "Broker", "Other"];

export default function PortalAccess() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const members = useQuery({ queryKey: ["portal-members"], queryFn: () => api<PortalMember[]>("/portal-members") });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api<DocItem[]>("/documents") });
  const [f, setF] = useState({ name: "", email: "", role: "Investor", handle: "", company: "" });
  const [team, setTeam] = useState<PortalMember | null>(null);
  const [ends, setEnds] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [tab, setTab] = useState<"people" | "activity" | "questions">("people");
  const questions = usePortalQuestions();
  const unanswered = (questions.data ?? []).filter((x) => !x.reply).length;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["portal-members"] });

  const add = useMutation({
    mutationFn: () => api<PortalMember & { email_sent: boolean }>("/portal-members", { body: { ...f, handle: f.handle.trim() || undefined, doc_ids: team?.doc_ids ?? [], digest: team?.digest ?? true, expires_on: ends, origin_url: BACKEND_URL } }),
    onSuccess: (m) => {
      refresh();
      setF({ name: "", email: "", role: "Investor", handle: "", company: "" });
      setTeam(null);
      setEnds(null);
      setOpen(m.id);
      if (m.email_sent) toast(`Invite sent · ID ${m.handle}`);
      else toast(`Access added (ID ${m.handle}) but the invite email failed. Tap Resend invite`, "error");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<PortalMember> }) => api<PortalMember>(`/portal-members/${id}`, { method: "PUT", body }),
    onSuccess: refresh,
    onError: (e: Error) => toast(e.message, "error"),
  });
  const resend = useMutation({ mutationFn: (id: string) => api(`/portal-members/${id}/resend`, { method: "POST" }), onSuccess: () => toast("Invite re-sent"), onError: (e: Error) => toast(e.message, "error") });
  const remove = useMutation({ mutationFn: (id: string) => api(`/portal-members/${id}`, { method: "DELETE" }), onSuccess: () => { refresh(); toast("Access removed", "info"); } });
  const portalUrl = `${BACKEND_URL}/api/portal`;

  return (
    <FormScreen title="Stakeholder portal" testID="portal-access-screen">
      <ExpiringAccessCard />
      <Card style={{ gap: space.sm }}>
        <Text style={s.title}>Give read-only access</Text>
        <Text style={s.muted}>
          Each person gets a personal <Text style={s.bold}>access code</Text> by email and creates their own password the first time they sign in. They can also sign in with their <Text style={s.bold}>name@buildassist</Text> ID or email and a one-time code. They see only this project, the documents you tick and the weekly updates.
        </Text>
        <Pressable onPress={async () => { await Clipboard.setStringAsync(portalUrl); toast("Portal link copied"); }} style={s.urlRow} testID="portal-copy-url">
          <Icon name="globe" size={16} color={colors.brand} />
          <Text style={s.url} numberOfLines={1}>{portalUrl}</Text>
          <Icon name="copy" size={14} color={colors.brand} />
        </Pressable>
      </Card>

      <View style={s.chips}>
        <Chip label="People" icon="users" selected={tab === "people"} onPress={() => setTab("people")} testID="portal-tab-people" />
        <Chip label="Activity" icon="activity" selected={tab === "activity"} onPress={() => setTab("activity")} testID="portal-tab-activity" />
        <Chip label={unanswered ? `Questions (${unanswered})` : "Questions"} icon="message-square" selected={tab === "questions"} onPress={() => setTab("questions")} testID="portal-tab-questions" />
      </View>
      {tab === "activity" && <ActivityPanel />}
      {tab === "questions" && <QuestionsPanel />}
      {tab === "people" && (
      <>
      <Text style={s.section}>{team ? `Add a teammate to ${team.company || team.name}` : "Invite a stakeholder"}</Text>
      {team && (
        <View style={s.teamNote} testID="portal-teammate-banner">
          <Text style={[s.muted, { flex: 1 }]}>{`They'll get their own access code and password, with the same role, documents and weekly updates as ${team.name}.`}</Text>
          <Pressable onPress={() => { setTeam(null); setF({ name: "", email: "", role: "Investor", handle: "", company: "" }); }} hitSlop={8} testID="portal-teammate-cancel"><Icon name="x" size={16} color={colors.muted} /></Pressable>
        </View>
      )}
      <Field label="Name" value={f.name} onChangeText={(v) => setF({ ...f, name: v })} placeholder="e.g. Dave Patel" testID="portal-name-input" />
      <Field label="Email (access code is sent here)" value={f.email} onChangeText={(v) => setF({ ...f, email: v })} keyboardType="email-address" autoCapitalize="none" testID="portal-email-input" />
      <Field label="Company / team (optional)" value={f.company} onChangeText={(v) => setF({ ...f, company: v })} placeholder="e.g. Northfield Lending" testID="portal-company-input" />
      <Field label="Sign-in ID (optional)" value={f.handle} onChangeText={(v) => setF({ ...f, handle: v.replace(/[^a-zA-Z0-9.]/g, "").toLowerCase() })} placeholder={(f.name.split(" ")[0] || "dave").toLowerCase()} autoCapitalize="none" testID="portal-handle-input" />
      <Text style={s.muted}>Their ID will be <Text style={s.bold}>{(f.handle || f.name.split(" ")[0] || "name").toLowerCase()}@buildassist</Text> (a number is added if taken).</Text>
      <View style={s.chips}>
        {ROLES.map((r) => <Chip key={r} label={r} selected={f.role === r} onPress={() => setF({ ...f, role: r })} testID={`portal-role-${r.replace(/\s+/g, "-").toLowerCase()}`} />)}
      </View>
      <AccessEndPicker key={ends ?? "none"} value={ends} onChange={setEnds} testID="portal-invite-ends" />
      <Button icon="user-plus" title="Send invite" disabled={!f.name.trim() || !EMAIL_RE.test(f.email.trim())} loading={add.isPending} onPress={() => add.mutate()} testID="portal-invite-button" />

      <Text style={s.section}>People with access ({members.data?.length ?? 0})</Text>
      {members.isLoading ? <ActivityIndicator color={colors.brand} /> : (members.data ?? []).length === 0 ? <Text style={s.muted} testID="portal-empty">Nobody yet.</Text> : null}
      {[...(members.data ?? [])].sort((a, b) => (a.company || "~").localeCompare(b.company || "~")).map((m) => (
        <Card key={m.id} style={{ gap: space.sm }} testID={`portal-member-${m.id}`}>
          <Pressable onPress={() => { tap(); setOpen(open === m.id ? null : m.id); }} style={{ flexDirection: "row", alignItems: "center", gap: space.md }} testID={`portal-member-toggle-${m.id}`}>
            <View style={{ flex: 1 }}>
              {m.company ? <Text style={s.company} testID={`portal-member-company-${m.id}`}>{m.company}</Text> : null}
              <Text style={s.name}>{m.name} · {m.role}{m.is_lead ? " · Team lead" : ""}</Text>
              <Text style={[s.muted, { color: colors.brand, fontFamily: fonts.semibold }]} testID={`portal-member-handle-${m.id}`}>{m.handle}</Text>
              <Text style={s.muted}>{m.email} · {m.doc_ids.length} document{m.doc_ids.length === 1 ? "" : "s"}{m.digest ? " · weekly updates" : ""} · {m.last_login ? `last seen ${new Date(m.last_login).toLocaleDateString("en-GB")}` : "not signed in yet"}</Text>
              <View style={[s.status, { backgroundColor: m.password_set ? colors.brandTertiary : colors.surfaceSecondary }]} testID={`portal-member-password-${m.id}`}>
                <Icon name={m.password_set ? "lock" : "key-round"} size={12} color={m.password_set ? colors.brand : colors.muted} />
                <Text style={[s.statusText, { color: m.password_set ? colors.brand : colors.muted }]}>{m.password_set ? "Password set" : "Access code sent · password not set yet"}</Text>
              </View>
              {(m.expires_on || m.expired) && (
                <View style={[s.status, { backgroundColor: m.expired ? colors.errorTint : colors.surfaceSecondary }]} testID={`portal-member-expiry-${m.id}`}>
                  <Icon name={m.expired ? "lock" : "calendar-clock"} size={12} color={m.expired ? colors.error : colors.muted} />
                  <Text style={[s.statusText, { color: m.expired ? colors.error : colors.muted }]}>{m.expired ? `Access ended ${fmtEnd(m.expires_on!)}` : `Access until ${fmtEnd(m.expires_on!)}`}</Text>
                </View>
              )}
            </View>
            <Icon name={open === m.id ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
          </Pressable>
          {open === m.id && (
            <View style={{ gap: space.sm }}>
              <View style={s.toggle}>
                <Text style={s.name}>Show weekly updates</Text>
                <Switch value={m.digest} onValueChange={(v) => update.mutate({ id: m.id, body: { digest: v } })} trackColor={{ true: colors.brand, false: colors.borderStrong }} thumbColor={colors.surface} testID={`portal-digest-switch-${m.id}`} />
              </View>
              <View style={s.toggle}>
                <View style={{ flex: 1 }}>
                  <Text style={s.name}>Team lead</Text>
                  <Text style={s.muted}>{m.company ? `Can invite and remove ${m.company} teammates from the portal` : "Add a company to make them a lead"}</Text>
                </View>
                <Switch value={m.is_lead} disabled={!m.company} onValueChange={(v) => update.mutate({ id: m.id, body: { is_lead: v } })} trackColor={{ true: colors.brand, false: colors.borderStrong }} thumbColor={colors.surface} testID={`portal-lead-switch-${m.id}`} />
              </View>
              <AccessEndPicker key={m.expires_on ?? "none"} value={m.expires_on} onSave={(v) => update.mutate({ id: m.id, body: { expires_on: v } }, { onSuccess: () => toast(v ? `Access now ends ${fmtEnd(v)}` : "End date removed") })} saving={update.isPending} testID={`portal-ends-${m.id}`} />
              {m.invited_by && <Text style={s.muted} testID={`portal-member-invited-by-${m.id}`}>Added by their team lead ({m.invited_by})</Text>}
              <Text style={s.label}>Documents they can see</Text>
              {(docs.data ?? []).length === 0 && <Text style={s.muted}>Upload documents first.</Text>}
              {(docs.data ?? []).map((d) => {
                const on = m.doc_ids.includes(d.id);
                return (
                  <Pressable key={d.id} onPress={() => update.mutate({ id: m.id, body: { doc_ids: on ? m.doc_ids.filter((x) => x !== d.id) : [...m.doc_ids, d.id] } })} style={[s.docRow, on && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]} testID={`portal-doc-${m.id}-${d.id}`}>
                    <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>{on && <Icon name="check" size={12} color={colors.onBrand} />}</View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.name} numberOfLines={1}>{d.title}</Text>
                      <Text style={s.muted}>{d.doc_type}</Text>
                    </View>
                  </Pressable>
                );
              })}
              <Button small variant="outline" icon="user-plus" title="Add a teammate" onPress={() => { tap(); setTeam(m); setF({ name: "", email: "", role: m.role, handle: "", company: m.company || m.name }); }} testID={`portal-add-teammate-${m.id}`} />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" icon="send" title={m.password_set ? "Resend invite" : "Resend access code"} loading={resend.isPending} onPress={() => resend.mutate(m.id)} style={{ flex: 1 }} testID={`portal-resend-${m.id}`} />
                <Button small variant="danger" icon="user-x" title="Remove" loading={remove.isPending} onPress={() => remove.mutate(m.id)} style={{ flex: 1 }} testID={`portal-remove-${m.id}`} />
              </View>
            </View>
          )}
        </Card>
      ))}
      </>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface, marginTop: space.sm },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  bold: { fontFamily: fonts.semibold, color: c.onSurface },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceSecondary },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  urlRow: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.md, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, minHeight: 44 },
  url: { flex: 1, fontFamily: fonts.medium, fontSize: 12, color: c.brand },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  toggle: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  docRow: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.sm, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  company: { fontFamily: fonts.bold, fontSize: 11, color: c.muted, letterSpacing: 0.6, textTransform: "uppercase" },
  status: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill, marginTop: 4 },
  statusText: { fontFamily: fonts.semibold, fontSize: 11 },
  teamNote: { flexDirection: "row", alignItems: "flex-start", gap: space.sm, padding: space.md, borderRadius: radius.md, backgroundColor: c.brandTertiary },
}));
