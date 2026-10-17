import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Chip, EmptyState, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { useProject } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Kind = "repair" | "snag" | "stage";
type Item = { id: string; kind: Kind; project_id: string; project_name: string; title: string; detail: string; priority: "low" | "medium" | "high"; date: string; overdue: boolean };
type Inbox = { items: Item[]; counts: Record<Kind | "overdue" | "total", number>; projects: number };

const KIND: Record<Kind, { label: string; icon: IconName }> = {
  repair: { label: "Tenant repair", icon: "wrench" },
  snag: { label: "Snag", icon: "list-checks" },
  stage: { label: "Stage", icon: "flag" },
};

export default function InboxScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { refresh } = useAuth();
  const project = useProject();
  const [filter, setFilter] = useState<Kind | "all">("all");
  const [opening, setOpening] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/inbox") });
  const items = (q.data?.items ?? []).filter((i) => filter === "all" || i.kind === filter);

  const open = async (i: Item) => {
    tap();
    setOpening(i.id);
    try {
      if (project.data?.id !== i.project_id) {
        await api(`/projects/${i.project_id}/activate`, { method: "POST" });
        await refresh();
        await queryClient.invalidateQueries();
      }
      router.push(i.kind === "stage" ? "/timeline" : "/snags");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setOpening(null);
    }
  };

  const c = q.data?.counts;
  return (
    <View style={s.root} testID="inbox-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="inbox-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={s.headerTitle}>My tasks</Text>
          {q.data && <Text style={s.muted} testID="inbox-summary">{c!.total} open · {c!.overdue} overdue · {q.data.projects} project{q.data.projects === 1 ? "" : "s"}</Text>}
        </View>
        <View style={{ width: 44 }} />
      </View>
      <View style={s.filters}>
        <Chip label={`All${c ? ` (${c.total})` : ""}`} selected={filter === "all"} onPress={() => setFilter("all")} testID="inbox-filter-all" />
        <Chip label={`Repairs${c ? ` (${c.repair})` : ""}`} icon="wrench" selected={filter === "repair"} onPress={() => setFilter("repair")} testID="inbox-filter-repair" />
        <Chip label={`Snags${c ? ` (${c.snag})` : ""}`} icon="list-checks" selected={filter === "snag"} onPress={() => setFilter("snag")} testID="inbox-filter-snag" />
        <Chip label={`Stages${c ? ` (${c.stage})` : ""}`} icon="flag" selected={filter === "stage"} onPress={() => setFilter("stage")} testID="inbox-filter-stage" />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}><Text style={s.muted}>Could not load your tasks.</Text><Button small title="Retry" onPress={() => q.refetch()} testID="inbox-retry" /></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.kind + i.id}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + space.xxl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListEmptyComponent={<EmptyState icon="circle-check" title="All caught up" subtitle="No open snags, tenant repairs or stages due in the next 30 days." testID="inbox-empty" />}
          renderItem={({ item: i }) => {
            const urgent = i.overdue || i.priority === "high";
            const tone = urgent ? colors.error : i.priority === "medium" ? colors.warning : colors.muted;
            return (
              <Pressable onPress={() => open(i)} testID={`inbox-item-${i.kind}-${i.id}`} style={({ pressed }) => [s.item, urgent && { borderColor: colors.error }, pressed && { opacity: 0.9 }]}>
                <View style={[s.kindIcon, i.kind === "repair" && { backgroundColor: colors.orangeTint }]}>
                  <Icon name={KIND[i.kind].icon} size={18} color={i.kind === "repair" ? colors.brandPrimary : colors.brand} />
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={s.title} numberOfLines={2}>{i.title}</Text>
                  <Text style={s.muted} numberOfLines={1}>{KIND[i.kind].label} · {i.project_name}{i.detail ? ` · ${i.detail}` : ""}</Text>
                  <Text style={[s.meta, { color: tone }]}>
                    {i.kind === "stage" ? (i.overdue ? `Overdue · due ${i.date}` : `Due ${i.date}`) : `${i.priority === "high" ? "Urgent" : i.priority === "medium" ? "Soon" : "Not urgent"} · reported ${i.date}`}
                  </Text>
                </View>
                {opening === i.id ? <ActivityIndicator color={colors.brand} /> : <Icon name="chevron-right" size={18} color={colors.muted} />}
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  filters: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, paddingHorizontal: space.lg, paddingVertical: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  item: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.md },
  kindIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  meta: { fontFamily: fonts.semibold, fontSize: 12 },
}));
