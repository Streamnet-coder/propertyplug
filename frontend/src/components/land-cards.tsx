import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { gbp, Project } from "@/src/api";
import { Card, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { DECISIONS, decisionDue } from "@/src/planning";
import { usePlanning } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

/** Value with vs without planning, and profit after purchase + project costs (the larger of budget or spend so far). */
export function LandUplift({ p }: { p: Project }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const without = p.value_without_planning;
  const withP = p.value_with_planning;
  if (!without && !withP) {
    return (
      <Pressable testID="land-uplift-empty" onPress={() => { tap(); router.push("/project-edit"); }} style={s.empty}>
        <Icon name="trending-up" size={18} color={colors.brandPrimary} />
        <Text style={s.emptyText}>Add land values with and without planning to see the uplift from approval</Text>
        <Icon name="chevron-right" size={18} color={colors.brandPrimary} />
      </Pressable>
    );
  }
  const gain = withP - without;
  const pct = without > 0 ? (gain / without) * 100 : 0;
  const costs = Math.max(p.total_budget, p.total_spent);
  const profitWith = withP - p.purchase_price - costs;
  const profitWithout = without - p.purchase_price - costs;
  return (
    <Card style={{ gap: space.md }} testID="land-uplift-card">
      <View style={s.between}>
        <Text style={s.title}>Planning uplift</Text>
        <Text style={[s.big, { color: gain >= 0 ? colors.success : colors.error }]} testID="land-uplift-gain">{gain >= 0 ? "+" : ""}{gbp(gain, 0, p.currency)}</Text>
      </View>
      <View style={s.row}>
        <View style={s.cell}><Text style={s.val} testID="land-value-without">{gbp(without, 0, p.currency)}</Text><Text style={s.muted}>without planning</Text></View>
        <View style={s.cell}><Text style={s.val} testID="land-value-with">{gbp(withP, 0, p.currency)}</Text><Text style={s.muted}>with planning</Text></View>
        <View style={s.cell}><Text style={[s.val, { color: gain >= 0 ? colors.success : colors.error }]} testID="land-uplift-pct">{without > 0 ? `${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%` : "-"}</Text><Text style={s.muted}>uplift</Text></View>
      </View>
      <View style={s.between}>
        <Text style={s.muted}>Profit if approved</Text>
        <Text style={[s.val, { color: profitWith >= 0 ? colors.success : colors.error }]} testID="land-profit-with">{gbp(profitWith, 0, p.currency)}</Text>
      </View>
      <View style={s.between}>
        <Text style={s.muted}>Profit if refused</Text>
        <Text style={[s.val, { color: profitWithout >= 0 ? colors.success : colors.error }]} testID="land-profit-without">{gbp(profitWithout, 0, p.currency)}</Text>
      </View>
      <Text style={s.muted}>After {gbp(p.purchase_price, 0, p.currency)} purchase and {gbp(costs, 0, p.currency)} costs</Text>
    </Card>
  );
}

/** Planning applications summary with the next pending decision as a reminder. */
export function PlanningCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = usePlanning();
  const apps = q.data ?? [];
  const next = apps.filter((a) => a.days_to_decision != null).sort((a, b) => a.days_to_decision! - b.days_to_decision!)[0];
  const urgent = next && next.days_to_decision! <= 14;
  const latest = apps[0];
  return (
    <Pressable testID="planning-card" onPress={() => { tap(); router.push("/planning"); }} style={({ pressed }) => [s.card, urgent && { borderColor: next.days_to_decision! < 0 ? colors.error : colors.brandPrimary, borderWidth: 1.5 }, pressed && { opacity: 0.9 }]}>
      <View style={s.iconBox}><Icon name="file-check" size={20} color={colors.brand} /></View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.title}>Planning applications</Text>
        {next ? (
          <Text style={[s.muted, urgent && { color: next.days_to_decision! < 0 ? colors.error : colors.brandPrimary, fontFamily: fonts.semibold }]} testID="planning-reminder">
            {next.reference || "Application"}: {decisionDue(next)}
          </Text>
        ) : (
          <Text style={s.muted} testID="planning-card-summary">{latest ? `${apps.length} application${apps.length === 1 ? "" : "s"} · latest ${DECISIONS[latest.decision].toLowerCase()}` : "Track references, key dates and decisions"}</Text>
        )}
      </View>
      <Icon name="chevron-right" size={18} color={colors.muted} />
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  between: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  row: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  title: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurfaceSecondary },
  big: { fontFamily: fonts.extrabold, fontSize: 20 },
  val: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  empty: { flexDirection: "row", alignItems: "center", gap: space.sm, backgroundColor: c.orangeTint, padding: space.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.orangeBorder },
  emptyText: { flex: 1, fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceSecondary },
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg },
  iconBox: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
}));
