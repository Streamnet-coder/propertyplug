import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Text, View } from "react-native";

import { api } from "@/src/api";
import { EmptyState, fonts, FormScreen, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Entry = { id: string; actor_name: string; is_owner: boolean; is_you: boolean; action: string; at: string };

const when = (iso: string) => {
  const d = new Date(iso);
  const mins = Math.round((Date.parse(new Date().toISOString()) - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
};

export default function ProjectActivity() {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["project-activity"], queryFn: () => api<Entry[]>("/project-activity") });

  return (
    <FormScreen title="Project activity" testID="project-activity-screen">
      <Text style={s.muted}>Every change on this project by you and your co-owners.</Text>
      {q.isLoading ? (
        <ActivityIndicator color={colors.brand} />
      ) : (
        <>
          {!q.data?.length && <EmptyState icon="history" title="No changes yet" subtitle="Edits to budget, snags, quotes, documents and more will appear here." testID="project-activity-empty" />}
          {(q.data ?? []).map((e) => (
            <View key={e.id} style={s.row} testID={`activity-row-${e.id}`}>
              <View style={[s.avatar, !e.is_owner && { backgroundColor: colors.orangeTint }]}>
                <Text style={[s.avatarText, !e.is_owner && { color: colors.brandPrimary }]}>{e.actor_name.charAt(0).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.text}>
                  <Text style={s.bold}>{e.is_you ? "You" : e.actor_name}</Text> {e.action}
                </Text>
                <Text style={s.muted}>{e.is_owner ? "Owner" : "Co-owner"} · {when(e.at)}</Text>
              </View>
            </View>
          ))}
        </>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  avatar: { width: 34, height: 34, borderRadius: radius.pill, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 14, color: c.brand },
  text: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurface },
  bold: { fontFamily: fonts.bold },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
}));
