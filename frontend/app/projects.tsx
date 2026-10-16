import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, Project, setCurrency } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { PortfolioCard } from "@/src/components/portfolio-card";
import { useAuth } from "@/src/auth";
import { queryClient } from "@/src/query-client";
import { useProjects } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function Projects() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const [confirm, setConfirm] = useState<string | null>(null);
  const q = useProjects();
  const { refresh } = useAuth();

  const activate = useMutation({
    mutationFn: (id: string) => api<Project>(`/projects/${id}/activate`, { method: "POST" }),
    onSuccess: async (p) => {
      setCurrency(p.currency);
      await queryClient.invalidateQueries();
      await refresh(); // plan + co-owner context follow the project's owner
      toast("Switched project");
      router.back();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      setConfirm(null);
      await queryClient.invalidateQueries();
      toast("Project deleted");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <View style={s.root} testID="projects-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="projects-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>My projects</Text>
        <Pressable testID="portfolio-map-button" onPress={() => { tap(); router.push("/portfolio-map"); }} style={s.back} hitSlop={10}>
          <Icon name="map" size={20} />
        </Pressable>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Failed to load projects.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="projects-retry-button" />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.md, paddingBottom: insets.bottom + 100 }}>
          <PortfolioCard />
          {q.data!.map((p) => {
            const pct = p.total_budget > 0 ? Math.min(100, Math.round((p.total_spent / p.total_budget) * 100)) : 0;
            return (
              <Pressable
                key={p.id}
                testID={`project-row-${p.id}`}
                onPress={() => { tap(); if (p.active) router.back(); else activate.mutate(p.id); }}
                style={({ pressed }) => [s.card, p.active && { borderColor: colors.brand, borderWidth: 2 }, pressed && { opacity: 0.85 }]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
                  <View style={[s.icon, p.active && { backgroundColor: colors.brand }]}>
                    <Icon name={p.property_type === "land" ? "land-plot" : "house"} size={20} color={p.active ? colors.onBrand : colors.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.name} numberOfLines={1}>{p.name}</Text>
                    <Text style={s.muted} numberOfLines={1}>{p.property_type === "land" ? `Land · ${p.plot_size ? `${p.plot_size} ${p.plot_unit} · ` : ""}` : ""}{p.address || "No address"}</Text>
                    {p.shared && (
                      <View style={s.sharedPill} testID={`project-shared-badge-${p.id}`}>
                        <Icon name="users" size={11} color={colors.brand} />
                        <Text style={s.sharedText}>Co-owner · {p.owner_name}</Text>
                      </View>
                    )}
                  </View>
                  <View style={s.curPill} testID={`project-currency-badge-${p.id}`}><Text style={s.curText}>{p.currency}</Text></View>
                  {p.active ? (
                    <View style={s.activePill}><Text style={s.activeText}>ACTIVE</Text></View>
                  ) : activate.isPending && activate.variables === p.id ? (
                    <ActivityIndicator color={colors.brand} />
                  ) : (
                    <Icon name="chevron-right" size={18} color={colors.muted} />
                  )}
                </View>
                <View style={s.statRow}>
                  <Text style={s.muted}>Spent <Text style={s.bold}>{gbp(p.total_spent, 0, p.currency)}</Text> / {gbp(p.total_budget, 0, p.currency)}</Text>
                  <Text style={s.muted}>{p.line_item_count} items</Text>
                </View>
                <View style={s.track}><View style={[s.fill, { width: `${pct}%` }]} /></View>
                {!p.active && !p.shared && (
                  confirm === p.id ? (
                    <View style={{ flexDirection: "row", gap: space.sm }}>
                      <Button small variant="outline" title="Cancel" onPress={() => setConfirm(null)} style={{ flex: 1 }} testID={`project-delete-cancel-${p.id}`} />
                      <Button small variant="danger" title="Delete forever" loading={remove.isPending} onPress={() => remove.mutate(p.id)} style={{ flex: 1 }} testID={`project-delete-confirm-${p.id}`} />
                    </View>
                  ) : (
                    <Pressable onPress={() => setConfirm(p.id)} testID={`project-delete-${p.id}`} hitSlop={8} style={{ alignSelf: "flex-start" }}>
                      <Text style={[s.muted, { color: colors.error }]}>Delete project</Text>
                    </Pressable>
                  )
                )}
              </Pressable>
            );
          })}
        </ScrollView>
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="New project" icon="plus" onPress={() => router.push({ pathname: "/project-edit", params: { mode: "new" } })} testID="new-project-button" />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    backgroundColor: c.surface,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  bold: { fontFamily: fonts.bold, color: c.onSurface },
  activePill: { backgroundColor: c.brandTertiary, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  activeText: { fontFamily: fonts.extrabold, fontSize: 10, color: c.brand, letterSpacing: 0.6 },
  statRow: { flexDirection: "row", justifyContent: "space-between" },
  track: { height: 6, borderRadius: 3, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  fill: { height: 6, borderRadius: 3, backgroundColor: c.brandPrimary },
  cta: { position: "absolute", left: space.lg, right: space.lg },
  curPill: { borderWidth: 1, borderColor: c.border, paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill },
  sharedPill: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: c.brandTertiary },
  sharedText: { fontFamily: fonts.semibold, fontSize: 11, color: c.brand },
  curText: { fontFamily: fonts.bold, fontSize: 10, color: c.muted, letterSpacing: 0.4 },
}));
