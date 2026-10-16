import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, PortalActivity, PortalQuestion } from "@/src/api";
import { Button, Card, Field, fonts, Icon, IconName, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const KIND: Record<string, { icon: IconName; label: (a: PortalActivity) => string }> = {
  login: { icon: "log-in", label: () => "Signed in to the portal" },
  view: { icon: "eye", label: () => "Viewed the project" },
  download: { icon: "download", label: (a) => `Downloaded ${a.doc_title} (${a.doc_type})` },
  team_invite: { icon: "user-plus", label: (a) => `Invited teammate ${a.detail ?? ""}` },
  team_remove: { icon: "user-x", label: (a) => `Removed teammate ${a.detail ?? ""}` },
};

export const usePortalQuestions = () => useQuery({ queryKey: ["portal-questions"], queryFn: () => api<PortalQuestion[]>("/portal-questions") });

export function ActivityPanel() {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["portal-activity"], queryFn: () => api<PortalActivity[]>("/portal-activity") });
  if (q.isLoading) return <ActivityIndicator color={colors.brand} />;
  const items = q.data ?? [];
  const downloads = items.filter((a) => a.kind === "download");
  const byDoc = Object.values(downloads.reduce<Record<string, { title: string; names: Set<string>; n: number }>>((acc, a) => {
    const k = a.doc_id ?? "";
    acc[k] = acc[k] ?? { title: a.doc_title ?? "", names: new Set(), n: 0 };
    acc[k].names.add(a.name);
    acc[k].n += 1;
    return acc;
  }, {}));

  return (
    <View style={{ gap: space.md }} testID="portal-activity-panel">
      {byDoc.length > 0 && (
        <Card style={{ gap: space.sm }} testID="portal-download-summary">
          <Text style={s.title}>Document downloads</Text>
          {byDoc.map((d) => (
            <View key={d.title} style={s.sumRow}>
              <Text style={[s.name, { flex: 1 }]} numberOfLines={1}>{d.title}</Text>
              <Text style={s.muted}>{d.n}× · {[...d.names].join(", ")}</Text>
            </View>
          ))}
        </Card>
      )}
      {items.length === 0 ? (
        <Text style={s.muted} testID="portal-activity-empty">No portal activity yet. You&apos;ll see sign-ins, views and downloads here.</Text>
      ) : (
        items.map((a) => {
          const k = KIND[a.kind] ?? KIND.view;
          return (
            <View key={a.id} style={s.row} testID={`portal-activity-${a.id}`}>
              <View style={s.icon}><Icon name={k.icon} size={16} color={colors.brand} /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.name}>{a.name}</Text>
                <Text style={s.body}>{k.label(a)}</Text>
              </View>
              <Text style={s.muted}>{when(a.at)}</Text>
            </View>
          );
        })
      )}
    </View>
  );
}

export function QuestionsPanel() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = usePortalQuestions();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const reply = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => api<PortalQuestion>(`/portal-questions/${id}/reply`, { body: { text } }),
    onSuccess: (r) => { queryClient.invalidateQueries({ queryKey: ["portal-questions"] }); setDrafts((d) => ({ ...d, [r.id]: "" })); toast(`Reply sent to ${r.name}`); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  if (q.isLoading) return <ActivityIndicator color={colors.brand} />;
  if (!(q.data ?? []).length) return <Text style={s.muted} testID="portal-questions-empty">No questions yet. Stakeholders can ask from the portal, and you&apos;ll get an email.</Text>;

  return (
    <View style={{ gap: space.md }} testID="portal-questions-panel">
      {q.data!.map((x) => (
        <Card key={x.id} style={{ gap: space.sm }} testID={`portal-question-${x.id}`}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
            <Text style={[s.name, { flex: 1 }]}>{x.name}</Text>
            <Text style={s.muted}>{when(x.created_at)}</Text>
          </View>
          <Text style={s.body}>{x.text}</Text>
          {x.reply ? (
            <View style={s.reply} testID={`portal-question-reply-${x.id}`}>
              <Text style={s.muted}>Your reply · {when(x.replied_at!)}</Text>
              <Text style={s.body}>{x.reply}</Text>
            </View>
          ) : (
            <>
              <Field label="Reply" value={drafts[x.id] ?? ""} onChangeText={(v) => setDrafts((d) => ({ ...d, [x.id]: v }))} multiline placeholder="Type your answer" testID={`portal-reply-input-${x.id}`} />
              <Button small icon="send" title="Send reply" disabled={!(drafts[x.id] ?? "").trim()} loading={reply.isPending} onPress={() => reply.mutate({ id: x.id, text: drafts[x.id].trim() })} testID={`portal-reply-send-${x.id}`} />
            </>
          )}
        </Card>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  body: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20 },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md, borderRadius: radius.md, backgroundColor: c.surface, borderWidth: 1, borderColor: c.border },
  icon: { width: 32, height: 32, borderRadius: 16, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  sumRow: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingTop: space.xs },
  reply: { padding: space.md, borderRadius: radius.md, backgroundColor: c.brandTertiary, gap: 2 },
}));
