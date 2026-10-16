import { useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PlanningApp } from "@/src/api";
import { Button, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, usePlanning } from "@/src/queries";
import { DECISIONS, decisionDue } from "@/src/planning";
import { makeStyles, useTheme } from "@/src/theme";

export default function Planning() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const q = usePlanning();
  const tone = (a: PlanningApp) =>
    a.decision === "approved" ? colors.success : a.decision === "refused" ? colors.error : a.days_to_decision != null && a.days_to_decision <= 14 ? colors.brandPrimary : colors.muted;

  const dates = (a: PlanningApp) =>
    [["Submitted", a.submitted_date], ["Validated", a.validated_date], ["Consultation ends", a.consultation_end], ["Target decision", a.target_decision_date], ["Decided", a.decision_date]]
      .filter(([, v]) => v) as [string, string][];

  return (
    <View style={s.root} testID="planning-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="planning-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Planning applications</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}><Text style={s.muted}>Could not load applications.</Text><Button small title="Retry" onPress={() => q.refetch()} testID="planning-retry-button" /></View>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(a) => a.id}
          contentContainerStyle={{ padding: space.lg, gap: space.md, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => invalidate("planning")} tintColor={colors.brand} />}
          ListEmptyComponent={<EmptyState icon="file-check" title="No applications yet" subtitle="Track each planning application, its key dates and the decision." testID="planning-empty" />}
          renderItem={({ item: a }) => (
            <Pressable testID={`planning-row-${a.id}`} onPress={() => { tap(); router.push({ pathname: "/planning-form", params: { id: a.id } }); }} style={({ pressed }) => [s.card, pressed && { opacity: 0.85 }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
                <View style={{ flex: 1 }}>
                  <Text style={s.name} numberOfLines={1}>{a.reference || "No reference"}</Text>
                  <Text style={s.muted} numberOfLines={1}>{[a.authority, a.description].filter(Boolean).join(" · ") || "Planning application"}</Text>
                </View>
                <View style={[s.pill, { borderColor: tone(a) }]}><Text style={[s.pillText, { color: tone(a) }]} testID={`planning-decision-${a.id}`}>{DECISIONS[a.decision]}</Text></View>
              </View>
              {decisionDue(a) && (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Icon name="calendar-clock" size={14} color={tone(a)} />
                  <Text style={[s.due, { color: tone(a) }]} testID={`planning-due-${a.id}`}>{decisionDue(a)}</Text>
                </View>
              )}
              <View style={s.dates}>
                {dates(a).map(([l, v]) => (
                  <View key={l} style={s.dateCell}><Text style={s.muted}>{l}</Text><Text style={s.dateVal}>{v}</Text></View>
                ))}
              </View>
            </Pressable>
          )}
        />
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="Add application" icon="plus" onPress={() => router.push("/planning-form")} testID="add-planning-button" />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  pill: { borderWidth: 1.5, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.bold, fontSize: 11 },
  due: { fontFamily: fonts.semibold, fontSize: 13 },
  dates: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  dateCell: { flexBasis: "47%", flexGrow: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  dateVal: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
