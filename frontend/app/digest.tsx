import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button, Card, fonts, Icon, IconName, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { DigestEmailCard } from "@/src/components/digest-email-card";
import { DigestShareCard } from "@/src/components/digest-share-card";
import { useQuery } from "@tanstack/react-query";

import { api, gbp } from "@/src/api";
import { useDigest, useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const fmt = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export default function DigestScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const [week, setWeek] = useState(0);
  const q = useDigest(week);
  const project = useProject();
  const link = useQuery({ queryKey: ["digest-link"], queryFn: () => api<{ url: string | null }>("/digest/share") });
  const d = q.data;
  const diff = d ? d.spend.total - d.prev_spend : 0;

  const Stat = ({ icon, label, value, testID }: { icon: IconName; label: string; value: string; testID: string }) => (
    <Card style={s.stat} testID={testID}>
      <Icon name={icon} size={18} color={colors.brand} />
      <Text style={s.statVal}>{value}</Text>
      <Text style={s.muted}>{label}</Text>
    </Card>
  );

  return (
    <View style={s.root} testID="digest-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="digest-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Weekly digest</Text>
        <View style={{ width: 44 }} />
      </View>
      <View style={s.weekBar}>
        <Pressable testID="digest-prev-week" onPress={() => { tap(); setWeek((w) => Math.min(52, w + 1)); }} style={s.iconBtn} hitSlop={6}>
          <Icon name="chevron-left" size={20} />
        </Pressable>
        <View style={{ alignItems: "center" }}>
          <Text style={s.weekTitle} testID="digest-week-label">{week === 0 ? "This week" : week === 1 ? "Last week" : `${week} weeks ago`}</Text>
          {d && <Text style={s.muted}>{fmt(d.week_start)} – {fmt(d.week_end)}</Text>}
        </View>
        <Pressable testID="digest-next-week" disabled={week === 0} onPress={() => { tap(); setWeek((w) => Math.max(0, w - 1)); }} style={[s.iconBtn, week === 0 && { opacity: 0.35 }]} hitSlop={6}>
          <Icon name="chevron-right" size={20} />
        </Pressable>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError || !d ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load this week.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="digest-retry-button" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: space.lg, gap: space.xl, paddingBottom: insets.bottom + space.xl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          <View style={s.hero} testID="digest-spend-card">
            <Text style={s.heroLabel}>Spent this week</Text>
            <Text style={s.heroBig} testID="digest-spend-total">{gbp(d.spend.total, 2)}</Text>
            <Text style={s.heroSub}>
              {d.spend.receipts_count} receipt{d.spend.receipts_count === 1 ? "" : "s"} · {d.spend.payments_count} stage payment{d.spend.payments_count === 1 ? "" : "s"}
              {"  ·  "}{diff === 0 ? "same as week before" : `${gbp(Math.abs(diff))} ${diff > 0 ? "more" : "less"} than week before`}
            </Text>
          </View>

          <View style={s.grid}>
            <Stat icon="check-check" label="Snags fixed" value={String(d.snags_fixed.length)} testID="digest-snags-fixed" />
            <Stat icon="flag" label="Stages done" value={String(d.milestones_done.length)} testID="digest-milestones-done" />
            <Stat icon="list-checks" label="Snags still open" value={String(d.snags_open_now)} testID="digest-snags-open" />
          </View>

          {d.spend.top.length > 0 && (
            <View>
              <SectionTitle title="Biggest spends" />
              <Card style={{ paddingVertical: space.xs }}>
                {d.spend.top.map((r, i) => (
                  <View key={i} style={[s.row, i > 0 && s.divider]}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.rowTitle} numberOfLines={1}>{r.title}</Text>
                      <Text style={s.muted}>{r.supplier} · {fmt(r.date)}</Text>
                    </View>
                    <Text style={s.rowTitle}>{gbp(r.amount, 2)}</Text>
                  </View>
                ))}
              </Card>
            </View>
          )}

          <View>
            <SectionTitle title="Milestones hit" />
            <Card style={{ paddingVertical: space.xs }}>
              {d.milestones_done.length ? d.milestones_done.map((m, i) => (
                <View key={m.id} style={[s.row, i > 0 && s.divider]}>
                  <View style={[s.dot, { backgroundColor: colors.success }]}><Icon name="check" size={12} color={colors.onSuccess} /></View>
                  <Text style={[s.rowTitle, { flex: 1 }]}>{m.name}</Text>
                </View>
              )) : <Text style={[s.muted, s.empty]}>No stages completed this week</Text>}
              {d.next_milestone && week === 0 && (
                <View style={[s.row, s.divider]} testID="digest-next-milestone">
                  <View style={[s.dot, { backgroundColor: colors.brandPrimary }]}><Icon name="arrow-right" size={12} color={colors.onBrandPrimary} /></View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.rowTitle}>Up next: {d.next_milestone.name}</Text>
                    {d.next_milestone.target_date ? <Text style={s.muted}>Target {fmt(d.next_milestone.target_date)}</Text> : null}
                  </View>
                </View>
              )}
            </Card>
          </View>

          <View>
            <SectionTitle title="Snags fixed" />
            <Card style={{ paddingVertical: space.xs }}>
              {d.snags_fixed.length ? d.snags_fixed.map((x, i) => (
                <View key={x.id} style={[s.row, i > 0 && s.divider]}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.rowTitle} numberOfLines={2}>{x.description}</Text>
                    <Text style={s.muted}>{x.room}{x.fixed_by ? ` · fixed by ${x.fixed_by}` : ""}</Text>
                  </View>
                </View>
              )) : <Text style={[s.muted, s.empty]}>No snags fixed this week{d.snags_opened ? ` · ${d.snags_opened} new logged` : ""}</Text>}
            </Card>
          </View>

          <DigestShareCard projectName={project.data?.name} />
          <DigestEmailCard hasLink={!!link.data?.url} />
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  weekBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  weekTitle: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  hero: { backgroundColor: c.brand, borderRadius: radius.lg, padding: space.lg, gap: 4 },
  heroLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  heroBig: { fontFamily: fonts.extrabold, fontSize: 30, color: c.onBrand, letterSpacing: -0.5 },
  heroSub: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  grid: { flexDirection: "row", gap: space.sm },
  stat: { flex: 1, padding: space.md, gap: 4 },
  statVal: { fontFamily: fonts.extrabold, fontSize: 22, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  dot: { width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  empty: { paddingVertical: space.lg, textAlign: "center" },
}));
