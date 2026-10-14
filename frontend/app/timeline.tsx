import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Milestone } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, useMilestones } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const NEXT: Record<Milestone["status"], Milestone["status"]> = { todo: "in_progress", in_progress: "done", done: "todo" };
const LABEL: Record<Milestone["status"], string> = { todo: "To do", in_progress: "In progress", done: "Done" };

const fmt = (d?: string | null) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : null);

export default function Timeline() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useMilestones();
  const list = q.data ?? [];
  const done = list.filter((m) => m.status === "done").length;
  const pct = list.length ? Math.round((done / list.length) * 100) : 0;
  const current = list.find((m) => m.status === "in_progress") ?? list.find((m) => m.status === "todo");
  const today = new Date().toISOString().slice(0, 10);

  const cycle = useMutation({
    mutationFn: (m: Milestone) => api(`/milestones/${m.id}`, { method: "PUT", body: { status: NEXT[m.status] } }),
    onSuccess: (_d, m) => {
      invalidate("milestones", "project", "projects");
      if (NEXT[m.status] === "done") toast(`${m.name} complete`);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const color = (st: Milestone["status"]) => (st === "done" ? colors.success : st === "in_progress" ? colors.brandPrimary : colors.borderStrong);

  return (
    <View style={s.root} testID="timeline-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="timeline-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Milestone timeline</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load milestones.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="timeline-retry-button" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: space.lg, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          <View style={s.summary} testID="timeline-summary">
            <Text style={s.sumLabel}>Project progress</Text>
            <Text style={s.sumBig} testID="timeline-progress-text">{done} of {list.length} stages · {pct}%</Text>
            <View style={s.bar}><View style={[s.barFill, { width: `${pct}%` }]} /></View>
            <Text style={s.sumLabel}>{current ? `Now: ${current.name}` : list.length ? "All stages complete" : "No stages yet"}</Text>
          </View>
          <Text style={[s.muted, { marginVertical: space.md }]}>Tap the circle to move a stage forward. Tap the stage to edit dates and notes.</Text>
          {list.map((m, i) => {
            const overdue = m.status !== "done" && !!m.target_date && m.target_date < today;
            return (
              <Animated.View key={m.id} entering={FadeInDown.delay(Math.min(i, 10) * 40)} style={s.row}>
                <View style={s.rail}>
                  <View style={[s.line, { opacity: i === 0 ? 0 : 1 }]} />
                  <Pressable
                    testID={`milestone-status-${m.id}`}
                    onPress={() => { tap(); cycle.mutate(m); }}
                    hitSlop={10}
                    style={[s.dot, { borderColor: color(m.status), backgroundColor: m.status === "todo" ? colors.surface : color(m.status) }]}
                  >
                    {m.status === "done" && <Icon name="check" size={14} color={colors.onSuccess} />}
                    {m.status === "in_progress" && <View style={s.innerDot} />}
                  </Pressable>
                  <View style={[s.line, { opacity: i === list.length - 1 ? 0 : 1 }, m.status === "done" && { backgroundColor: colors.success }]} />
                </View>
                <Pressable
                  testID={`milestone-row-${m.id}`}
                  onPress={() => { tap(); router.push({ pathname: "/milestone-form", params: { id: m.id } }); }}
                  style={({ pressed }) => [s.card, m.status === "in_progress" && { borderColor: colors.brandPrimary }, pressed && { opacity: 0.85 }]}
                >
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={[s.name, m.status === "done" && { color: colors.muted }]}>{m.name}</Text>
                    <Text style={[s.muted, overdue && { color: colors.error }]}>
                      {m.status === "done" && m.completed_at
                        ? `Completed ${new Date(m.completed_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
                        : m.target_date
                          ? `${overdue ? "Overdue · " : "Target "}${fmt(m.target_date)}`
                          : "No target date"}
                    </Text>
                    {m.notes ? <Text style={s.notes} numberOfLines={2}>{m.notes}</Text> : null}
                  </View>
                  <View style={[s.pill, { backgroundColor: m.status === "done" ? colors.brandTertiary : m.status === "in_progress" ? colors.orangeTint : colors.surfaceTertiary }]}>
                    <Text style={[s.pillText, { color: m.status === "done" ? colors.brand : m.status === "in_progress" ? colors.brandPrimary : colors.muted }]}>{LABEL[m.status]}</Text>
                  </View>
                </Pressable>
              </Animated.View>
            );
          })}
        </ScrollView>
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="Add stage" icon="plus" onPress={() => router.push("/milestone-form")} testID="add-milestone-button" />
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
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  summary: { backgroundColor: c.brand, borderRadius: radius.lg, padding: space.lg, gap: 6 },
  sumLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  sumBig: { fontFamily: fonts.extrabold, fontSize: 22, color: c.onBrand },
  bar: { height: 8, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.25)", overflow: "hidden", marginVertical: 4 },
  barFill: { height: 8, borderRadius: 4, backgroundColor: c.brandPrimary },
  row: { flexDirection: "row", gap: space.md, minHeight: 76 },
  rail: { width: 28, alignItems: "center" },
  line: { flex: 1, width: 2, backgroundColor: c.border },
  dot: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, alignItems: "center", justifyContent: "center" },
  innerDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.surface },
  card: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: space.md,
    marginVertical: space.xs,
  },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  notes: { fontFamily: fonts.regular, fontSize: 12, color: c.onSurfaceTertiary, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.bold, fontSize: 10 },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
