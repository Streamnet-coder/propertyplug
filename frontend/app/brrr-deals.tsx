import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BrrrDeal, gbp } from "@/src/api";
import { Button, Card, EmptyState, fonts, Icon, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { BrrrFigures, calcBrrr } from "@/src/report";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const MAX_COMPARE = 3;
const pct = (v: number) => (Number.isFinite(v) ? `${v.toFixed(1)}%` : "Infinite");
const leftLabel = (v: number) => (v <= 0 ? `${gbp(-v)} out` : gbp(v));

/** Comparison rows: how to show each figure and whether higher or lower wins. */
const ROWS: { label: string; get: (f: BrrrFigures) => number; show: (f: BrrrFigures) => string; best: "low" | "high" | null }[] = [
  { label: "Money left in", get: (f) => f.leftIn, show: (f) => leftLabel(f.leftIn), best: "low" },
  { label: "Cash needed upfront", get: (f) => f.cashNeeded, show: (f) => gbp(f.cashNeeded), best: "low" },
  { label: "Cash-on-cash ROI", get: (f) => (Number.isFinite(f.roi) ? f.roi : 1e9), show: (f) => pct(f.roi), best: "high" },
  { label: "Cashflow / month", get: (f) => f.cashflow, show: (f) => gbp(f.cashflow), best: "high" },
  { label: "Gross yield", get: (f) => f.yieldPct, show: (f) => pct(f.yieldPct), best: "high" },
  { label: "Equity retained", get: (f) => f.equity, show: (f) => gbp(f.equity), best: "high" },
  { label: "Months to refinance", get: (f) => f.months ?? 0, show: (f) => `${f.months ?? 0} mo`, best: "low" },
  { label: "Bridging & holding", get: (f) => f.financeCost + f.holdingTotal, show: (f) => gbp(f.financeCost + f.holdingTotal), best: "low" },
  { label: "Total invested", get: (f) => f.invested, show: (f) => gbp(f.invested), best: null },
  { label: "Purchase price", get: (f) => f.purchase, show: (f) => gbp(f.purchase), best: null },
  { label: "Refurb", get: (f) => f.refurb, show: (f) => gbp(f.refurb), best: null },
  { label: "End valuation", get: (f) => f.valuation, show: (f) => gbp(f.valuation), best: null },
  { label: "Refinance amount", get: (f) => f.refi, show: (f) => gbp(f.refi), best: null },
  { label: "Monthly rent", get: (f) => f.rent, show: (f) => gbp(f.rent), best: null },
];

export default function BrrrDeals() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useQuery({ queryKey: ["brrr-deals"], queryFn: () => api<BrrrDeal[]>("/brrr/deals") });
  const [picked, setPicked] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const figs = useMemo(() => Object.fromEntries((q.data ?? []).map((d) => [d.id, calcBrrr(d.inputs)])), [q.data]);
  const compared = (q.data ?? []).filter((d) => picked.includes(d.id));

  const del = useMutation({
    mutationFn: (id: string) => api(`/brrr/deals/${id}`, { method: "DELETE" }),
    onSuccess: async (_, id) => { setPicked((p) => p.filter((x) => x !== id)); setConfirm(null); await invalidate("brrr-deals"); toast("Deal deleted"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const toggle = (id: string) => {
    tap();
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX_COMPARE ? (toast(`Compare up to ${MAX_COMPARE} deals at a time`, "error"), p) : [...p, id]));
  };

  return (
    <View style={s.root} testID="brrr-deals-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="brrr-deals-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>Saved BRRR deals</Text>
        <Pressable testID="brrr-deals-new-button" onPress={() => { tap(); router.push("/brrr"); }} style={s.iconBtn} hitSlop={6} accessibilityLabel="New deal"><Icon name="plus" size={20} /></Pressable>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}><Text style={s.muted}>{(q.error as Error).message}</Text><Button small title="Retry" onPress={() => q.refetch()} testID="brrr-deals-retry" /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          {!q.data?.length ? (
            <EmptyState icon="calculator" title="No saved deals yet" subtitle="Run the numbers in the BRRR calculator and tap Save deal to compare options here." action="Open calculator" onAction={() => router.push("/brrr")} testID="brrr-deals-empty" />
          ) : (
            <>
              <Text style={s.muted}>Tick up to {MAX_COMPARE} deals to compare them side by side.</Text>
              {q.data.map((d) => {
                const f = figs[d.id];
                const on = picked.includes(d.id);
                return (
                  <Pressable key={d.id} onPress={() => toggle(d.id)} testID={`brrr-deal-${d.id}`} style={({ pressed }) => [s.deal, on && { borderColor: colors.brand, borderWidth: 2 }, pressed && { opacity: 0.9 }]}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
                      <View style={[s.check, on && { backgroundColor: colors.brand, borderColor: colors.brand }]} testID={`brrr-deal-check-${d.id}`}>
                        {on && <Icon name="check" size={14} color={colors.onBrand} />}
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={s.name} numberOfLines={1}>{d.name}</Text>
                        <Text style={s.muted}>Updated {d.updated_at.slice(0, 10)} · {d.inputs.months} mo to refinance</Text>
                      </View>
                      <Pressable testID={`brrr-deal-open-${d.id}`} onPress={() => { tap(); router.push({ pathname: "/brrr", params: { deal: d.id } }); }} style={s.iconBtn} hitSlop={6} accessibilityLabel="Edit deal"><Icon name="pencil" size={16} /></Pressable>
                      <Pressable testID={`brrr-deal-delete-${d.id}`} onPress={() => { tap(); confirm === d.id ? del.mutate(d.id) : setConfirm(d.id); }} style={[s.iconBtn, confirm === d.id && { backgroundColor: colors.errorTint }]} hitSlop={6} accessibilityLabel="Delete deal">
                        {del.isPending && del.variables === d.id ? <ActivityIndicator color={colors.error} /> : <Icon name="trash-2" size={16} color={confirm === d.id ? colors.error : undefined} />}
                      </Pressable>
                    </View>
                    {confirm === d.id && <Text style={[s.muted, { color: colors.error }]}>Tap the bin again to delete this deal</Text>}
                    <View style={s.cells}>
                      <Cell v={leftLabel(f.leftIn)} l="left in" />
                      <Cell v={gbp(f.cashflow)} l="cashflow / mo" color={f.cashflow < 0 ? colors.error : colors.success} />
                      <Cell v={pct(f.roi)} l="ROI" />
                    </View>
                  </Pressable>
                );
              })}
              {compared.length >= 2 && <Compare deals={compared} figs={figs} />}
            </>
          )}
        </ScrollView>
      )}
    </View>
  );
}

function Cell({ v, l, color }: { v: string; l: string; color?: string }) {
  const s = useStyles();
  return <View style={s.cell}><Text style={[s.cellVal, color ? { color } : null]} numberOfLines={1}>{v}</Text><Text style={s.muted}>{l}</Text></View>;
}

function Compare({ deals, figs }: { deals: BrrrDeal[]; figs: Record<string, BrrrFigures> }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View testID="brrr-compare">
      <SectionTitle title={`Comparing ${deals.length} deals`} />
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View>
            <View style={[s.tr, s.thead]}>
              <Text style={[s.td, s.labelCol, s.th]}>Figure</Text>
              {deals.map((d) => <Text key={d.id} style={[s.td, s.th]} numberOfLines={2}>{d.name}</Text>)}
            </View>
            {ROWS.map((r) => {
              const vals = deals.map((d) => r.get(figs[d.id]));
              const target = r.best === "low" ? Math.min(...vals) : r.best === "high" ? Math.max(...vals) : null;
              const tie = vals.every((v) => v === vals[0]);
              return (
                <View key={r.label} style={s.tr} testID={`brrr-compare-row-${r.label}`}>
                  <Text style={[s.td, s.labelCol]}>{r.label}</Text>
                  {deals.map((d, i) => {
                    const win = target !== null && !tie && vals[i] === target;
                    return (
                      <View key={d.id} style={[s.td, win && { backgroundColor: colors.brandTertiary }]}>
                        <Text style={[s.val, win && { color: colors.success }]} numberOfLines={1}>{r.show(figs[d.id])}{win ? " ✓" : ""}</Text>
                      </View>
                    );
                  })}
                </View>
              );
            })}
          </View>
        </ScrollView>
      </Card>
      <Text style={[s.muted, { marginTop: space.sm }]}>✓ marks the best figure in each row. Money left in includes bridging interest, fees and holding costs until refinance.</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md, padding: space.lg },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  deal: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  check: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: c.border, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  tr: { flexDirection: "row", borderTopWidth: 1, borderTopColor: c.divider },
  thead: { borderTopWidth: 0, backgroundColor: c.surfaceSecondary },
  td: { width: 128, paddingHorizontal: space.md, paddingVertical: space.sm, justifyContent: "center" },
  labelCol: { width: 150, fontFamily: fonts.medium, fontSize: 12, color: c.onSurfaceTertiary },
  th: { fontFamily: fonts.bold, fontSize: 12, color: c.onSurface },
  val: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
}));
