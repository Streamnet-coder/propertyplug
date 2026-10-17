import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, Snag } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Person = { kind: "team" | "trade"; id: string; name: string; email: string; role: string };

/** Appoint a co-owner, manager or trade to a snag / reported problem. They're emailed the job with a link to mark it fixed with a photo. */
export function AssignSheet({ snag, onClose }: { snag: Snag | null; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const router = useRouter();
  const q = useQuery({ queryKey: ["snag-assignees"], queryFn: () => api<{ team: Person[]; trades: Person[] }>("/snag-assignees"), enabled: !!snag });

  const assign = useMutation({
    mutationFn: (p: Person) => api<{ emailed: boolean; texted: boolean; assignee: string }>(`/snags/${snag!.id}/assign`, { body: { kind: p.kind, id: p.id, origin_url: BACKEND_URL } }),
    onSuccess: (r) => {
      ["snags", "inbox"].forEach((k) => queryClient.invalidateQueries({ queryKey: [k] }));
      toast(r.emailed ? `Assigned to ${r.assignee} · job emailed${r.texted ? " & texted" : ""}` : `Assigned to ${r.assignee}`);
      onClose();
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const current = snag?.assigned_to?.id;
  const row = (p: Person) => (
    <Pressable key={p.kind + p.id} onPress={() => { tap(); assign.mutate(p); }} disabled={assign.isPending}
      style={({ pressed }) => [s.row, current === p.id && { borderColor: colors.brand }, pressed && { opacity: 0.85 }]} testID={`assign-${p.kind}-${p.id}`}>
      <View style={s.avatar}><Icon name={p.kind === "team" ? "user-round" : "hard-hat"} size={18} color={colors.brand} /></View>
      <View style={{ flex: 1 }}>
        <Text style={s.name}>{p.name}</Text>
        <Text style={s.muted} numberOfLines={1}>{p.role}{p.email ? ` · ${p.email}` : " · no email, add one to send the job"}</Text>
      </View>
      {assign.isPending && assign.variables?.id === p.id ? <ActivityIndicator color={colors.brand} /> : current === p.id ? <Icon name="check" size={18} color={colors.brand} /> : <Icon name="send" size={16} color={colors.muted} />}
    </Pressable>
  );

  const empty = q.data && !q.data.team.length && !q.data.trades.length;
  return (
    <Modal visible={!!snag} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="assign-sheet">
          <Text style={s.title}>Assign to your team</Text>
          <Text style={s.muted} numberOfLines={2}>{snag?.description} · {snag?.room}</Text>
          {q.isLoading ? <ActivityIndicator color={colors.brand} /> : (
            <ScrollView style={{ maxHeight: 380 }} contentContainerStyle={{ gap: space.sm }}>
              {!!q.data?.team.length && <Text style={s.section}>Co-owners & managers</Text>}
              {q.data?.team.map(row)}
              {!!q.data?.trades.length && <Text style={s.section}>Trades</Text>}
              {q.data?.trades.map(row)}
              {empty && (
                <View style={{ gap: space.sm }} testID="assign-empty">
                  <Text style={s.muted}>No team yet. Invite a manager or add a trade with an email address.</Text>
                  <Button small variant="outline" icon="users" title="Co-owners & managers" onPress={() => { onClose(); router.push("/co-owners"); }} testID="assign-invite-team" />
                </View>
              )}
            </ScrollView>
          )}
          <Text style={s.muted}>They get an email with the issue, photo and a link to mark it fixed, plus gentle reminders if it's still open after a few days. The tenant is told when it's done.</Text>
          <Button variant="outline" title="Close" onPress={onClose} testID="assign-close" />
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  section: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6, marginTop: space.xs },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, minHeight: 56 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
}));
