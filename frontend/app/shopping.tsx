import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import { ActivityIndicator, Pressable, RefreshControl, SectionList, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, ShoppingItem } from "@/src/api";
import { Button, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, useShopping } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function Shopping() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useShopping();
  const all = useMemo(() => q.data ?? [], [q.data]);
  const done = all.filter((x) => x.checked).length;
  const left = all.filter((x) => !x.checked).reduce((a, x) => a + x.est_cost, 0);

  const sections = useMemo(() => {
    const by: Record<string, ShoppingItem[]> = {};
    all.forEach((x) => (by[x.supplier || "Any merchant"] ??= []).push(x));
    return Object.entries(by)
      .map(([title, data]) => ({ title, data: [...data].sort((a, b) => Number(a.checked) - Number(b.checked)) }))
      .sort((a, b) => a.title.localeCompare(b.title));
  }, [all]);

  const toggle = useMutation({
    mutationFn: (x: ShoppingItem) => api(`/shopping/${x.id}`, { method: "PUT", body: { checked: !x.checked } }),
    onSuccess: () => invalidate("shopping"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/shopping/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidate("shopping"),
  });
  const clear = useMutation({
    mutationFn: () => api<{ deleted: number }>("/shopping/checked", { method: "DELETE" }),
    onSuccess: (d) => { invalidate("shopping"); toast(`Cleared ${d.deleted} ticked item${d.deleted === 1 ? "" : "s"}`); },
  });

  return (
    <View style={s.root} testID="shopping-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.topRow}>
          <Pressable testID="shopping-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
            <Icon name="arrow-left" size={22} />
          </Pressable>
          <Text style={[s.headerTitle, { flex: 1, marginLeft: space.md }]}>Shopping list</Text>
          {done > 0 && (
            <Pressable testID="shopping-clear-ticked" onPress={() => { tap(); clear.mutate(); }} style={s.clearBtn} hitSlop={6}>
              <Icon name="trash-2" size={16} color={colors.error} />
              <Text style={s.clearText}>Clear ticked</Text>
            </Pressable>
          )}
        </View>
        <View style={s.summary} testID="shopping-summary">
          <Text style={s.sumBig}>{all.length - done} to buy</Text>
          <Text style={s.muted}>{done} of {all.length} ticked · about {gbp(left)} left to spend</Text>
        </View>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load your list.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="shopping-retry-button" />
        </View>
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(x) => x.id}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListEmptyComponent={<EmptyState icon="shopping-cart" title="Your list is empty" subtitle="Add budget line items or one-off bits, then tick them off at the merchant." testID="shopping-empty" />}
          renderSectionHeader={({ section }) => (
            <View style={s.secHead}>
              <Icon name="store" size={16} color={colors.brand} />
              <Text style={s.secTitle}>{section.title}</Text>
              <Text style={s.muted}>{section.data.filter((x) => !x.checked).length} left</Text>
            </View>
          )}
          renderItem={({ item }) => (
            <Pressable testID={`shopping-row-${item.id}`} onPress={() => { tap(); toggle.mutate(item); }} style={[s.card, item.checked && { opacity: 0.55 }]}>
              <View style={[s.check, item.checked && { backgroundColor: colors.success, borderColor: colors.success }]}>
                {item.checked && <Icon name="check" size={14} color={colors.onSuccess} />}
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[s.name, item.checked && { textDecorationLine: "line-through" }]} numberOfLines={2}>{item.name}</Text>
                <Text style={s.muted}>{[item.qty && `Qty ${item.qty}`, item.est_cost ? `~${gbp(item.est_cost)}` : "", item.line_item_id ? "From budget" : ""].filter(Boolean).join(" · ") || "One-off item"}</Text>
              </View>
              <Pressable testID={`shopping-delete-${item.id}`} onPress={() => { tap(); remove.mutate(item.id); }} hitSlop={10} style={s.del}>
                <Icon name="x" size={16} color={colors.muted} />
              </Pressable>
            </Pressable>
          )}
        />
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="Add items" icon="plus" onPress={() => router.push("/shopping-add")} testID="shopping-add-button" />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, gap: space.md, borderBottomWidth: 1, borderBottomColor: c.border },
  topRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  clearBtn: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.errorTint },
  clearText: { fontFamily: fonts.semibold, fontSize: 13, color: c.error },
  summary: { gap: 2 },
  sumBig: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  secHead: { flexDirection: "row", alignItems: "center", gap: space.sm, marginTop: space.md, marginBottom: space.xs },
  secTitle: { flex: 1, fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md, minHeight: 60 },
  check: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  del: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
