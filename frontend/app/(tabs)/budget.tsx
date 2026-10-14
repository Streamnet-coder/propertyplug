import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Category, gbp, LineItem } from "@/src/api";
import { Button, Chip, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { invalidate, useLineItems } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const FILTERS: ("All" | Category)[] = ["All", "Hard Cost", "Soft Cost", "Contingency"];

export default function Budget() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const q = useLineItems();

  const items = useMemo(() => (q.data ?? []).filter((i) => filter === "All" || i.category === filter), [q.data, filter]);
  const totals = items.reduce((a, i) => ({ b: a.b + i.budgeted, a: a.a + i.actual }), { b: 0, a: 0 });

  const renderItem = ({ item, index }: { item: LineItem; index: number }) => {
    const variance = item.budgeted - item.actual;
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
          </View>
          <View style={{ alignItems: "flex-end", gap: 2 }}>
            <Text style={s.amt}>{gbp(item.actual)}</Text>
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
        <Text style={s.title}>Budget</Text>
        <Text style={s.sub}>Line items, suppliers & variance</Text>
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
              <View style={s.summary} testID="budget-summary">
                <View>
                  <Text style={s.meta}>Budgeted</Text>
                  <Text style={s.sumVal}>{gbp(totals.b)}</Text>
                </View>
                <View>
                  <Text style={s.meta}>Actual</Text>
                  <Text style={s.sumVal}>{gbp(totals.a)}</Text>
                </View>
                <View>
                  <Text style={s.meta}>Variance</Text>
                  <Text style={[s.sumVal, { color: totals.b - totals.a < 0 ? colors.error : colors.success }]}>{gbp(totals.b - totals.a)}</Text>
                </View>
              </View>
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
}));
