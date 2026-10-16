import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Category, gbp, LineItem } from "@/src/api";
import { Button, Chip, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { PdfButton } from "@/src/components/pdf-button";
import { usesNativeTabs } from "@/src/navigation";
import { shareBudgetPdf } from "@/src/report";
import { invalidate, useLineItems, useSpendTrend } from "@/src/queries";
import { CategoryBars, SpendTrendChart } from "@/src/components/spend-charts";
import { makeStyles, useTheme } from "@/src/theme";

const FILTERS: ("All" | Category | "Alerts")[] = ["All", "Hard Cost", "Soft Cost", "Contingency", "Alerts"];

export default function Budget() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const q = useLineItems();
  const trend = useSpendTrend();

  const items = useMemo(() => (q.data ?? []).filter((i) => filter === "All" || (filter === "Alerts" ? !!i.alert : i.category === filter)), [q.data, filter]);
  const totals = items.reduce((a, i) => ({ b: a.b + i.budgeted, a: a.a + i.spent }), { b: 0, a: 0 });
  const over = (q.data ?? []).filter((i) => i.alert === "over");
  const near = (q.data ?? []).filter((i) => i.alert === "near");

  const renderItem = ({ item, index }: { item: LineItem; index: number }) => {
    const variance = item.budgeted - item.spent;
    const pct = item.budgeted > 0 ? Math.round((item.spent / item.budgeted) * 100) : 0;
    return (
      <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 40)}>
        <Pressable
          testID={`line-item-${item.id}`}
          onPress={() => { tap(); router.push({ pathname: "/item-form", params: { id: item.id } }); }}
          style={({ pressed }) => [s.item, pressed && { backgroundColor: colors.surfaceTertiary }]}
        >
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={s.itemName} numberOfLines={1}>{item.name}</Text>
            <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
              <View style={s.tag}><Text style={s.tagText}>{item.category}</Text></View>
              <Text style={s.meta} numberOfLines={1}>{item.supplier || "No supplier"} · {item.status}</Text>
            </View>
            {item.alert && (
              <View style={[s.alertPill, { backgroundColor: item.alert === "over" ? colors.errorTint : colors.orangeTint }]} testID={`variance-${item.alert}-${item.id}`}>
                <Icon name="triangle-alert" size={12} color={item.alert === "over" ? colors.error : colors.brandPrimary} />
                <Text style={[s.alertPillText, { color: item.alert === "over" ? colors.error : colors.brandPrimary }]}>{item.alert === "over" ? `Over budget · ${pct}%` : `${pct}% of budget used`}</Text>
              </View>
            )}
            {item.linked_spend > 0 && <Text style={s.meta}>Includes {gbp(item.linked_spend, 2)} from shopping receipts</Text>}
          </View>
          <View style={{ alignItems: "flex-end", gap: 2 }}>
            <Text style={s.amt}>{gbp(item.spent)}</Text>
            <Text style={s.meta}>of {gbp(item.budgeted)}</Text>
            <Text style={[s.variance, { color: variance < 0 ? colors.error : colors.success }]}>
              {variance < 0 ? "Over " : "Under "}{gbp(Math.abs(variance))}
            </Text>
          </View>
        </Pressable>
      </Animated.View>
    );
  };

  return (
    <View style={s.root} testID="budget-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>Budget</Text>
            <Text style={s.sub}>Line items, suppliers & variance</Text>
          </View>
          <PdfButton onGenerate={shareBudgetPdf} testID="budget-pdf-button" />
        </View>
      </View>
      <View style={s.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {FILTERS.map((f) => (
            <Chip key={f} label={f} selected={filter === f} onPress={() => setFilter(f)} testID={`budget-filter-${f.replace(" ", "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>

      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.meta}>Could not fetch budget data.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="budget-retry-button" />
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: space.lg, paddingBottom: bottomChrome + 100, gap: space.sm }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => invalidate("line-items", "project")} tintColor={colors.brand} />}
          ListHeaderComponent={
            <View style={{ gap: space.md, marginBottom: space.sm }}>
              <Pressable testID="ai-estimate-banner" onPress={() => { tap(); router.push("/ai-estimate"); }} style={s.ai}>
                <View style={s.aiIcon}><Icon name="sparkles" size={20} color={colors.onBrand} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={s.aiTitle}>AI cost estimate</Text>
                  <Text style={s.aiSub}>Describe the job, get UK supplier prices in seconds</Text>
                </View>
                <Icon name="chevron-right" size={20} color={colors.onBrand} />
              </Pressable>
              <Pressable testID="payment-schedule-banner" onPress={() => { tap(); router.push("/payments"); }} style={s.payCard}>
                <Icon name="calendar-check" size={20} color={colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={s.itemName}>Payment schedule</Text>
                  <Text style={s.meta}>Deposits & stage payments against accepted quotes</Text>
                </View>
                <Icon name="chevron-right" size={18} color={colors.muted} />
              </Pressable>
              <Pressable testID="shopping-list-banner" onPress={() => { tap(); router.push("/shopping"); }} style={s.payCard}>
                <Icon name="shopping-cart" size={20} color={colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={s.itemName}>Shopping list</Text>
                  <Text style={s.meta}>Turn line items into a checklist for the merchant</Text>
                </View>
                <Icon name="chevron-right" size={18} color={colors.muted} />
              </Pressable>
              {over.length + near.length > 0 && (
                <Pressable testID="budget-variance-banner" onPress={() => { tap(); setFilter("Alerts"); }} style={[s.payCard, { borderColor: over.length ? colors.error : colors.brandPrimary }]}>
                  <Icon name="triangle-alert" size={20} color={over.length ? colors.error : colors.brandPrimary} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.itemName}>{over.length ? `${over.length} item${over.length === 1 ? "" : "s"} over budget` : `${near.length} item${near.length === 1 ? "" : "s"} near budget`}</Text>
                    <Text style={s.meta} numberOfLines={2}>{[...over, ...near].map((i) => i.name).join(", ")}</Text>
                  </View>
                  <Text style={[s.meta, { color: colors.brand, fontFamily: fonts.semibold }]}>View</Text>
                </Pressable>
              )}
              <View style={s.summary} testID="budget-summary">
                <View>
                  <Text style={s.meta}>Budgeted</Text>
                  <Text style={s.sumVal}>{gbp(totals.b)}</Text>
                </View>
                <View>
                  <Text style={s.meta}>Spent</Text>
                  <Text style={s.sumVal}>{gbp(totals.a)}</Text>
                </View>
                <View>
                  <Text style={s.meta}>Variance</Text>
                  <Text style={[s.sumVal, { color: totals.b - totals.a < 0 ? colors.error : colors.success }]}>{gbp(totals.b - totals.a)}</Text>
                </View>
              </View>
              {trend.data && <SpendTrendChart trend={trend.data} />}
              <CategoryBars items={q.data ?? []} />
            </View>
          }
          ListEmptyComponent={<EmptyState icon="clipboard-list" title="No line items logged" subtitle="Add your first cost to start tracking variance." testID="budget-empty" />}
        />
      )}
      <View style={[s.cta, { bottom: bottomChrome + space.lg }]}>
        <Button title="Add Item" icon="plus" onPress={() => router.push("/item-form")} testID="add-line-item-button" />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  alertPill: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  alertPillText: { fontFamily: fonts.semibold, fontSize: 11 },
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  title: { fontFamily: fonts.extrabold, fontSize: 28, color: c.onSurface, letterSpacing: -0.5 },
  sub: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
  chipRow: { height: 56, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, justifyContent: "center" },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  ai: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.brand, padding: space.lg, borderRadius: radius.lg },
  aiIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
  aiTitle: { fontFamily: fonts.bold, fontSize: 16, color: c.onBrand },
  aiSub: { fontFamily: fonts.regular, fontSize: 12, color: c.onBrand, opacity: 0.85, marginTop: 2 },
  summary: {
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: space.lg,
  },
  sumVal: { fontFamily: fonts.extrabold, fontSize: 17, color: c.onSurface, marginTop: 2 },
  item: {
    flexDirection: "row",
    gap: space.md,
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: space.lg,
  },
  itemName: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  tag: { backgroundColor: c.brandTertiary, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  tagText: { fontFamily: fonts.semibold, fontSize: 10, color: c.onBrandTertiary },
  meta: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, flexShrink: 1 },
  amt: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  variance: { fontFamily: fonts.semibold, fontSize: 11 },
  cta: { position: "absolute", left: space.lg, right: space.lg },
  payCard: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.lg },
}));
