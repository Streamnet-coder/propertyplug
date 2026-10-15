import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Stakeholder } from "@/src/api";
import { EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const ago = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");

export default function Stakeholders() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["stakeholders"], queryFn: () => api<Stakeholder[]>("/stakeholders") });

  return (
    <View style={s.root} testID="stakeholders-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="stakeholders-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.headerTitle}>Message log</Text>
          <Text style={s.muted}>Every conversation with your team & partners</Text>
        </View>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : (
        <FlatList
          data={q.data ?? []}
          keyExtractor={(p) => p.key}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + space.xl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListEmptyComponent={<EmptyState icon="users" title="No stakeholders yet" subtitle="Add trades, lenders or weekly update partners to start tracking messages." testID="stakeholders-empty" />}
          renderItem={({ item }) => (
            <Pressable
              testID={`stakeholder-row-${item.key}`}
              onPress={() => { tap(); router.push({ pathname: "/stakeholder", params: { name: item.name, email: item.email, phone: item.phone, role: item.role } }); }}
              style={s.row}
            >
              <View style={[s.avatar, item.source === "partner" && { backgroundColor: colors.orangeTint }]}>
                <Text style={[s.initials, item.source === "partner" && { color: colors.brandPrimary }]}>{item.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
                  <Text style={[s.name, { flex: 1 }]} numberOfLines={1}>{item.name}</Text>
                  <Text style={s.muted}>{ago(item.last_at)}</Text>
                </View>
                <Text style={s.muted} numberOfLines={1}>{item.role}</Text>
                <Text style={[s.last, !item.last_summary && { color: colors.muted }]} numberOfLines={1}>
                  {item.last_summary ? `${item.last_direction === "in" ? "← " : "→ "}${item.last_summary}` : "No messages yet"}
                </Text>
              </View>
              {item.count ? <View style={s.badge}><Text style={s.badgeText}>{item.count}</Text></View> : null}
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", gap: space.md, paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  initials: { fontFamily: fonts.bold, fontSize: 15, color: c.brand },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  last: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceSecondary },
  badge: { minWidth: 24, height: 24, borderRadius: 12, paddingHorizontal: 6, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  badgeText: { fontFamily: fonts.bold, fontSize: 12, color: c.onBrand },
}));
