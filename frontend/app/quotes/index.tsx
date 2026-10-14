import { useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { gbp } from "@/src/api";
import { Button, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useQuotes } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

export default function Quotes() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuotes();

  return (
    <View style={s.root} testID="quotes-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="quotes-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Quote requests</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load quote requests.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="quotes-retry-button" />
        </View>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: space.lg, gap: space.md, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListEmptyComponent={
            <EmptyState icon="file-text" title="No quote requests yet" subtitle="Describe a job once and send it to several trades. Their prices land here side by side." testID="quotes-empty" />
          }
          renderItem={({ item, index }) => {
            const priced = item.quotes.filter((x) => x.amount != null);
            const low = priced.length ? Math.min(...priced.map((x) => x.amount!)) : null;
            const accepted = item.quotes.find((x) => x.status === "accepted");
            return (
              <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 40)}>
                <Pressable testID={`quote-request-${item.id}`} onPress={() => { tap(); router.push(`/quotes/${item.id}`); }} style={({ pressed }) => [s.card, pressed && { opacity: 0.85 }]}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
                    <Text style={s.title} numberOfLines={1}>{item.title}</Text>
                    {accepted ? (
                      <View style={[s.pill, { backgroundColor: colors.brandTertiary }]}><Text style={[s.pillText, { color: colors.brand }]}>AWARDED</Text></View>
                    ) : null}
                  </View>
                  <Text style={s.muted} numberOfLines={2}>{item.description}</Text>
                  <View style={s.stats}>
                    <Text style={s.muted}><Text style={s.bold}>{priced.length}</Text> of {item.quotes.length} quotes in</Text>
                    <Text style={s.muted}>
                      {accepted ? `${accepted.name} · ${gbp(accepted.amount ?? 0)}` : low != null ? <>Lowest <Text style={[s.bold, { color: colors.success }]}>{gbp(low)}</Text></> : "Awaiting prices"}
                    </Text>
                  </View>
                </Pressable>
              </Animated.View>
            );
          }}
        />
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="New quote request" icon="plus" onPress={() => router.push("/quotes/new")} testID="new-quote-request-button" />
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
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.sm },
  title: { flex: 1, fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  bold: { fontFamily: fonts.bold, color: c.onSurface },
  stats: { flexDirection: "row", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: c.divider, paddingTop: space.sm },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.extrabold, fontSize: 10, letterSpacing: 0.5 },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
