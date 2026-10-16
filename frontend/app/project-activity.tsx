import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";

import { api } from "@/src/api";
import { Button, Chip, EmptyState, fonts, FormScreen, radius, space } from "@/src/components/ui";
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
  const q = useQuery({ queryKey: ["project-activity"], queryFn: () => api<Entry[]>("/project-activity?limit=300") });
  const [who, setWho] = useState<string | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const all = useMemo(() => q.data ?? [], [q.data]);
  const areaOf = (e: Entry) => e.action.split(" ").slice(1).join(" ");
  const people = useMemo(() => [...new Set(all.map((e) => e.actor_name))], [all]);
  const areas = useMemo(() => [...new Set(all.map(areaOf))].sort(), [all]);
  const rows = all.filter((e) => (!who || e.actor_name === who) && (!area || areaOf(e) === area));
  const slug = (x: string) => x.replace(/\s+/g, "-").toLowerCase();

  return (
    <FormScreen title="Project activity" testID="project-activity-screen">
      <Text style={s.muted}>Every change on this project by you and your co-owners.</Text>
      {q.isLoading ? (
        <ActivityIndicator color={colors.brand} />
      ) : (
        <>
          {all.length > 0 && (
            <View style={{ gap: space.sm }} testID="activity-filters">
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
                <Chip label="Everyone" icon="users" selected={!who} onPress={() => setWho(null)} testID="activity-filter-person-all" />
                {people.map((p) => (
                  <Chip key={p} label={p} selected={who === p} onPress={() => setWho(who === p ? null : p)} testID={`activity-filter-person-${slug(p)}`} />
                ))}
              </ScrollView>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
                <Chip label="All areas" selected={!area} onPress={() => setArea(null)} testID="activity-filter-area-all" />
                {areas.map((a) => (
                  <Chip key={a} label={a.charAt(0).toUpperCase() + a.slice(1)} selected={area === a} onPress={() => setArea(area === a ? null : a)} testID={`activity-filter-area-${slug(a)}`} />
                ))}
              </ScrollView>
              <Text style={s.muted} testID="activity-count">{rows.length} of {all.length} changes</Text>
            </View>
          )}
          {all.length > 0 && !rows.length && (
            <View style={{ alignItems: "center", gap: space.sm, paddingVertical: space.lg }} testID="activity-filter-empty">
              <Text style={s.muted}>No changes match these filters.</Text>
              <Button small variant="outline" title="Clear filters" onPress={() => { setWho(null); setArea(null); }} testID="activity-clear-filters" />
            </View>
          )}
          {!all.length && <EmptyState icon="history" title="No changes yet" subtitle="Edits to budget, snags, quotes, documents and more will appear here." testID="project-activity-empty" />}
          {rows.map((e) => (
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
