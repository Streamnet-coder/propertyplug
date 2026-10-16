import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api, DocItem } from "@/src/api";
import { Button, Card, Field, fonts, Icon, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type DocRequest = { id: string; title: string; note: string; status: "open" | "fulfilled" | "declined"; reply: string; name: string; company: string; created_at: string; doc_titles: string[] | null };

/** Owner side of team-lead document requests: share documents with the requester's team, or decline. */
export function DocRequestsPanel({ docs }: { docs: DocItem[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["portal-members", "doc-requests"], queryFn: () => api<DocRequest[]>("/portal-doc-requests") });
  const [open, setOpen] = useState<string | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  const [reply, setReply] = useState("");
  const answer = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "fulfilled" | "declined" }) => api(`/portal-doc-requests/${id}`, { method: "PUT", body: { status, reply, doc_ids: status === "fulfilled" ? pick : [] } }),
    onSuccess: async (_r, v) => {
      setOpen(null); setPick([]); setReply("");
      await queryClient.invalidateQueries({ queryKey: ["portal-members"] });
      toast(v.status === "fulfilled" ? "Shared with their team" : "Request declined");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const rows = q.data ?? [];
  if (!rows.length) return null;
  const openCount = rows.filter((r) => r.status === "open").length;

  return (
    <Card style={{ gap: space.md }} testID="doc-requests-panel">
      <Text style={s.title}>Document requests{openCount ? ` · ${openCount} waiting` : ""}</Text>
      {rows.map((r) => (
        <View key={r.id} style={s.item} testID={`doc-request-${r.id}`}>
          <Pressable disabled={r.status !== "open"} onPress={() => { tap(); setOpen(open === r.id ? null : r.id); setPick([]); setReply(""); }} style={s.row} testID={`doc-request-toggle-${r.id}`}>
            <Icon name={r.status === "open" ? "file-question" : r.status === "fulfilled" ? "file-check" : "file-x"} size={18} color={r.status === "open" ? colors.brandPrimary : r.status === "fulfilled" ? colors.success : colors.muted} />
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{r.title}</Text>
              <Text style={s.muted}>{r.name}{r.company ? ` · ${r.company}` : ""} · {new Date(r.created_at).toLocaleDateString("en-GB")}{r.note ? ` · "${r.note}"` : ""}</Text>
              {r.status !== "open" && <Text style={s.muted} testID={`doc-request-status-${r.id}`}>{r.status === "fulfilled" ? `Shared${r.doc_titles?.length ? `: ${r.doc_titles.join(", ")}` : ""}` : "Declined"}{r.reply ? ` · "${r.reply}"` : ""}</Text>}
            </View>
            {r.status === "open" && <Icon name={open === r.id ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />}
          </Pressable>
          {open === r.id && (
            <View style={{ gap: space.sm }}>
              <Text style={s.muted}>Tick documents to share with {r.company || r.name}&apos;s team:</Text>
              {docs.length === 0 && <Text style={s.muted}>No documents uploaded yet. Upload it in Documents first.</Text>}
              {docs.map((d) => {
                const on = pick.includes(d.id);
                return (
                  <Pressable key={d.id} onPress={() => setPick(on ? pick.filter((x) => x !== d.id) : [...pick, d.id])} style={s.row} testID={`doc-request-pick-${r.id}-${d.id}`}>
                    <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>{on && <Icon name="check" size={14} color={colors.onBrand} />}</View>
                    <Text style={[s.name, { flex: 1, fontSize: 13 }]} numberOfLines={1}>{d.title}</Text>
                  </Pressable>
                );
              })}
              <Field label="Reply (optional)" value={reply} onChangeText={setReply} placeholder="e.g. Uploaded the latest certificate" testID={`doc-request-reply-${r.id}`} />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" title="Decline" style={{ flex: 1 }} loading={answer.isPending && answer.variables?.status === "declined"} onPress={() => answer.mutate({ id: r.id, status: "declined" })} testID={`doc-request-decline-${r.id}`} />
                <Button small title={pick.length ? `Share ${pick.length}` : "Mark done"} style={{ flex: 1 }} loading={answer.isPending && answer.variables?.status === "fulfilled"} onPress={() => answer.mutate({ id: r.id, status: "fulfilled" })} testID={`doc-request-fulfil-${r.id}`} />
              </View>
            </View>
          )}
        </View>
      ))}
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  item: { gap: space.sm, paddingTop: space.sm, borderTopWidth: 1, borderTopColor: c.border },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 40 },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
}));
