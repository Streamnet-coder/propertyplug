import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, MapPin, Project, setCurrency } from "@/src/api";
import { Button, Chip, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { mapHtml } from "@/src/components/map-html";
import { PortfolioMapView } from "@/src/components/portfolio-map-view";
import { FilterTotals } from "@/src/components/filter-totals";
import { queryClient } from "@/src/query-client";
import { usePortfolioMap } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function PortfolioMap() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const q = usePortfolioMap();
  const all = useMemo(() => q.data ?? [], [q.data]);
  const [type, setType] = useState<"all" | "residential" | "land">("all");
  const [country, setCountry] = useState<string | null>(null);
  const [cur, setCur] = useState<string | null>(null);
  const countries = useMemo(() => [...new Set(all.map((p) => p.country ?? "Unknown"))].sort(), [all]);
  const currencies = useMemo(() => [...new Set(all.map((p) => p.currency))].sort(), [all]);
  const pins = useMemo(
    () => all.filter((p) => (type === "all" || p.property_type === type) && (!country || (p.country ?? "Unknown") === country) && (!cur || p.currency === cur)),
    [all, type, country, cur],
  );
  const filtered = type !== "all" || !!country || !!cur;
  const html = useMemo(() => mapHtml(pins, { brand: colors.brand, land: colors.accent, active: colors.brandPrimary }), [pins, colors]);
  const missing = pins.filter((p) => p.lat == null);

  // Pins can only be edited on the active project, so switch first then open the editor.
  const fixPin = useMutation({
    mutationFn: async (p: MapPin) => (p.active ? null : api<Project>(`/projects/${p.id}/activate`, { method: "POST" })),
    onSuccess: async (res) => {
      if (res) { setCurrency(res.currency); await queryClient.invalidateQueries(); }
      router.push("/project-edit");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <View style={s.root} testID="portfolio-map-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="map-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Portfolio map</Text>
        <View style={{ width: 44 }} />
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /><Text style={s.muted}>Locating your properties…</Text></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load the map.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="map-retry-button" />
        </View>
      ) : (
        <>
          <View style={s.filters} testID="map-filters">
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
              {(["all", "residential", "land"] as const).map((t) => (
                <Chip key={t} label={{ all: "All", residential: "Property", land: "Land" }[t]} selected={type === t} onPress={() => setType(t)} testID={`map-filter-type-${t}`} />
              ))}
              <View style={s.sep} />
              {currencies.map((c) => (
                <Chip key={c} label={c} selected={cur === c} onPress={() => setCur(cur === c ? null : c)} testID={`map-filter-currency-${c}`} />
              ))}
            </ScrollView>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
              <Chip label="All countries" icon="globe" selected={!country} onPress={() => setCountry(null)} testID="map-filter-country-all" />
              {countries.map((c) => (
                <Chip key={c} label={c} selected={country === c} onPress={() => setCountry(country === c ? null : c)} testID={`map-filter-country-${c.replace(/\s+/g, "-").toLowerCase()}`} />
              ))}
            </ScrollView>
          </View>
          <View style={{ flex: 1 }}><PortfolioMapView html={html} /></View>
          <FilterTotals pins={pins} filtered={filtered} />
          <ScrollView style={s.list} contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + space.lg }}>
            <View style={s.legend}>
              <Dot color={colors.brandPrimary} label="Active" />
              <Dot color={colors.brand} label="Property" />
              <Dot color={colors.accent} label="Land" />
              <Text style={[s.muted, { marginLeft: "auto" }]} testID="map-pin-count">{pins.length - missing.length}/{pins.length} on map{filtered ? ` · ${all.length} total` : ""}</Text>
            </View>
            {pins.length === 0 && (
              <View style={{ alignItems: "center", gap: space.sm, paddingVertical: space.md }} testID="map-filter-empty">
                <Text style={s.muted}>No properties match these filters.</Text>
                <Button small variant="outline" title="Clear filters" onPress={() => { setType("all"); setCountry(null); setCur(null); }} testID="map-clear-filters" />
              </View>
            )}
            {pins.map((p) => (
              <View key={p.id} style={s.row} testID={`map-row-${p.id}`}>
                <Icon name={p.property_type === "land" ? "land-plot" : "house"} size={18} color={p.lat == null ? colors.muted : colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={s.name} numberOfLines={1}>{p.name}</Text>
                  <Text style={s.muted} numberOfLines={1}>
                    {p.lat == null ? (p.address ? "Address not found · add a pin" : "No address · add a pin") : `${p.address} · ${gbp(p.estimated_valuation, 0, p.currency)}`}
                  </Text>
                  {p.country && <Text style={s.muted} numberOfLines={1}>{p.country} · {p.currency}</Text>}
                </View>
                <Pressable onPress={() => { tap(); fixPin.mutate(p); }} hitSlop={8} testID={`map-fix-pin-${p.id}`} style={s.fix}>
                  {fixPin.isPending && fixPin.variables?.id === p.id ? <ActivityIndicator size="small" color={colors.brand} /> : <Text style={s.fixText}>{p.lat == null ? "Add pin" : "Edit"}</Text>}
                </Pressable>
              </View>
            ))}
            <Text style={s.foot}>Locations come from each address via OpenStreetMap. Set exact coordinates in Edit project.</Text>
          </ScrollView>
        </>
      )}
    </View>
  );
}

function Dot({ color, label }: { color: string; label: string }) {
  const s = useStyles();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color }} />
      <Text style={s.muted}>{label}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  filters: { backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, paddingVertical: space.sm, gap: space.sm },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  sep: { width: 1, height: 24, backgroundColor: c.border },
  list: { maxHeight: 280, backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.border },
  legend: { flexDirection: "row", alignItems: "center", gap: space.md },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.sm },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  foot: { fontFamily: fonts.regular, fontSize: 11, color: c.muted, marginTop: space.sm },
  fix: { minHeight: 36, minWidth: 64, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  fixText: { fontFamily: fonts.bold, fontSize: 12, color: c.brand },
}));
