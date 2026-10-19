import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, RentRoll, RentRollRow } from "@/src/api";
import { Button, Card, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { MAX_CONTENT, useLayout } from "@/src/layout";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function RentRollScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [year, setYear] = useState(new Date().getFullYear());
  const q = useQuery({ queryKey: ["rent-roll", year], queryFn: () => api<RentRoll>(`/portfolio/rent-roll?year=${year}`) });
  const d = q.data;
  const home = d?.home_currency;
  const { wide } = useLayout();

  return (
    <View style={s.root} testID="rent-roll-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="rent-roll-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>Rent roll</Text>
        <Pressable testID="rent-roll-arrears-button" onPress={() => { tap(); router.push("/arrears"); }} style={s.iconBtn} hitSlop={6} accessibilityLabel="Rent arrears"><Icon name="bell-ring" size={20} /></Pressable>
      </View>
      <View style={s.yearBar}>
        <Pressable testID="rent-roll-prev-year" onPress={() => { tap(); setYear(year - 1); }} style={s.iconBtn} hitSlop={6}><Icon name="chevron-left" size={20} /></Pressable>
        <Text style={s.year} testID="rent-roll-year">{year}</Text>
        <Pressable testID="rent-roll-next-year" onPress={() => { tap(); setYear(year + 1); }} style={s.iconBtn} hitSlop={6}><Icon name="chevron-right" size={20} /></Pressable>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError || !d ? (
        <View style={s.center}><Text style={s.muted}>Could not load the rent roll.</Text><Button small title="Retry" onPress={() => q.refetch()} testID="rent-roll-retry" /></View>
      ) : (
        <ScrollView
          contentContainerStyle={[{ padding: wide ? space.xl : space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }, wide && s.contained]}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
        >
          <View style={wide ? s.cols : s.stack}>
          <View style={wide ? s.colSide : s.stack} testID={wide ? "rent-roll-side-column" : undefined}>
          <Card style={{ gap: space.md }} testID="rent-roll-totals">
            <Text style={s.label}>Portfolio net cashflow {year} · {home}</Text>
            <Text style={[s.big, { color: d.totals.net < 0 ? colors.error : colors.success }]} testID="rent-roll-net">{gbp(d.totals.net, 0, home)}</Text>
            <View style={s.cells}>
              <Cell v={gbp(d.totals.received, 0, home)} l="rent received" id="rent-roll-received" />
              <Cell v={gbp(d.totals.expenses, 0, home)} l="letting costs" id="rent-roll-expenses" />
              <Cell v={gbp(d.totals.arrears, 0, home)} l="arrears" id="rent-roll-arrears" color={d.totals.arrears > 0 ? colors.error : undefined} />
            </View>
            <View style={s.cells}>
              <Cell v={String(d.counts.properties)} l="let properties" id="rent-roll-properties" />
              <Cell v={`${d.counts.active}/${d.counts.tenancies}`} l="active tenancies" id="rent-roll-active" />
              <Cell v={gbp(d.totals.active_rent, 0, home)} l="rent / month" id="rent-roll-monthly" />
            </View>
            {d.properties.some((p) => p.currency !== home) && (
              <Text style={s.muted}>Converted to {home} at rates from {d.rate_date}{d.stale ? " (cached)" : ""}.</Text>
            )}
          </Card>
          </View>
          <View style={wide ? s.colMain : s.stack}>
          {d.properties.length === 0 ? (
            <EmptyState icon="key-round" title="No rental records yet" subtitle={`Add tenancies under Rent & tenancy on any property to see them rolled up here for ${year}.`} testID="rent-roll-empty" />
          ) : (
            d.properties.map((p) => <PropertyRow key={p.id} p={p} home={home!} />)
          )}
          </View>
          </View>
        </ScrollView>
      )}
    </View>
  );
}

function Cell({ v, l, id, color }: { v: string; l: string; id: string; color?: string }) {
  const s = useStyles();
  return <View style={s.cell}><Text style={[s.cellVal, color ? { color } : null]} numberOfLines={1} testID={id}>{v}</Text><Text style={s.muted}>{l}</Text></View>;
}

function PropertyRow({ p, home }: { p: RentRollRow; home: RentRoll["home_currency"] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const open = async () => {
    tap();
    setBusy(true);
    try {
      await api(`/projects/${p.id}/activate`, { method: "POST" });
      await queryClient.invalidateQueries();
      router.push("/rentals");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const fx = p.currency !== home;
  return (
    <Pressable onPress={open} testID={`rent-roll-row-${p.id}`} style={({ pressed }) => [s.row, p.arrears > 0 && { borderColor: colors.error }, pressed && { opacity: 0.9 }]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <Text style={s.name} numberOfLines={1}>{p.name}{p.shared ? " · shared" : ""}</Text>
          <Text style={s.muted} numberOfLines={1}>{p.address || "No address"}</Text>
        </View>
        {busy ? <ActivityIndicator color={colors.brand} /> : <Icon name="chevron-right" size={18} color={colors.muted} />}
      </View>
      <View style={s.cells}>
        <Cell v={gbp(p.received, 0, p.currency)} l="received" id={`rent-roll-row-received-${p.id}`} />
        <Cell v={gbp(p.net, 0, p.currency)} l="net" id={`rent-roll-row-net-${p.id}`} color={p.net < 0 ? colors.error : colors.success} />
        <Cell v={gbp(p.arrears, 0, p.currency)} l="arrears" id={`rent-roll-row-arrears-${p.id}`} color={p.arrears > 0 ? colors.error : undefined} />
      </View>
      {fx && <Text style={s.muted}>≈ {gbp(p.home.net, 0, home)} net in {home}</Text>}
      {p.tenants.map((t) => (
        <View key={t.name + t.end_date} style={s.tenant}>
          <Icon name="user" size={14} color={colors.muted} />
          <Text style={[s.tenantText, { flex: 1 }]} numberOfLines={1}>{t.name} · {t.status}{t.end_date ? ` · ends ${t.end_date}` : " · rolling"}</Text>
          <Text style={[s.tenantText, t.arrears > 0 && { color: colors.error }]}>{gbp(t.rent, 0, p.currency)}/mo{t.arrears > 0 ? ` · ${gbp(t.arrears, 0, p.currency)} owed` : ""}</Text>
        </View>
      ))}
      {p.late_months > 0 && <Text style={[s.muted, { color: colors.error }]}>{p.late_months} late month{p.late_months === 1 ? "" : "s"} in {p.tenancies > 1 ? "these tenancies" : "this tenancy"}</Text>}
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  contained: { width: "100%", maxWidth: MAX_CONTENT, alignSelf: "center" },
  stack: { gap: space.lg },
  cols: { flexDirection: "row", alignItems: "flex-start", gap: space.xl },
  colSide: { width: 420, gap: space.lg },
  colMain: { flex: 1, minWidth: 0, gap: space.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  yearBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.xl, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  year: { fontFamily: fonts.extrabold, fontSize: 18, color: c.onSurface, minWidth: 60, textAlign: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  big: { fontFamily: fonts.extrabold, fontSize: 32, letterSpacing: -0.8 },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  row: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  tenant: { flexDirection: "row", alignItems: "center", gap: space.sm },
  tenantText: { fontFamily: fonts.medium, fontSize: 12, color: c.onSurfaceTertiary },
}));
