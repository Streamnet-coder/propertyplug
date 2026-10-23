import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, RentComps } from "@/src/api";
import { ListingButtons } from "@/src/components/credits";
import { Button, Card, Chip, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useLayout } from "@/src/layout";
import { listingLinks } from "@/src/listings";
import { useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const PC_RE = /\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b/i;
const BEDS = [{ k: "1", l: "1 bed" }, { k: "2", l: "2 bed" }, { k: "3", l: "3 bed" }, { k: "4", l: "4+ bed" }] as const;
const TYPES = [{ k: "flat", l: "Flat" }, { k: "terraced", l: "Terraced" }, { k: "semi", l: "Semi" }, { k: "detached", l: "Detached" }] as const;

export default function RentComparables() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useLayout();
  const { data: p } = useProject();
  const projectPc = p?.address.match(PC_RE)?.[1]?.toUpperCase() ?? "";
  const [input, setInput] = useState<string | null>(null);
  const [postcode, setPostcode] = useState<string | null>(null);
  const [beds, setBeds] = useState<string>("all");
  const [value, setValue] = useState<string | null>(null);
  const pc = postcode ?? projectPc;
  const q = useQuery({ queryKey: ["rent-comps", pc], queryFn: () => api<RentComps>(`/rent-comparables?postcode=${encodeURIComponent(pc)}`), enabled: !!pc, retry: false, staleTime: 60 * 60 * 1000 });
  const d = q.data;
  const rent = (d ? d.local.prices[beds] ?? d.local.prices.all : 0) ?? 0;
  const val = value ?? (p?.estimated_valuation ? String(p.estimated_valuation) : "");
  const yieldPct = rent && Number(val) > 0 ? ((rent * 12) / Number(val)) * 100 : 0;
  const search = () => { tap(); const v = (input ?? pc).trim().toUpperCase(); if (v) setPostcode(v); };
  const vs = (a?: number | null, b?: number | null) => (a && b ? `${a >= b ? "+" : ""}${Math.round((a / b - 1) * 100)}%` : "–");

  const left = (
    <>
      <Card style={{ gap: space.md }} testID="rent-controls">
        <View style={{ flexDirection: "row", gap: space.sm, alignItems: "flex-end" }}>
          <View style={{ flex: 1 }}>
            <Field label="Postcode" value={input ?? pc} onChangeText={setInput} autoCapitalize="characters" selectTextOnFocus maxLength={8} placeholder="e.g. NG7 1AA" onSubmitEditing={search} returnKeyType="search" testID="rent-postcode-input" />
          </View>
          <Button title="Search" icon="search" onPress={search} testID="rent-search-button" />
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          <Chip label="All homes" selected={beds === "all"} onPress={() => setBeds("all")} testID="rent-beds-all" />
          {BEDS.map((b) => <Chip key={b.k} label={b.l} selected={beds === b.k} onPress={() => setBeds(b.k)} testID={`rent-beds-${b.k}`} />)}
        </ScrollView>
      </Card>
      {pc ? <ListingButtons links={listingLinks(pc, 0.5, "rent")} title="Live rental listings nearby" testID="rent-listings" /> : null}
    </>
  );

  const body = !pc ? (
    <Card style={{ alignItems: "center", gap: space.sm }} testID="rent-no-postcode"><Icon name="map-pin" size={28} color={colors.brand} /><Text style={s.muted}>Enter a UK postcode to see typical rents for the area.</Text></Card>
  ) : q.isLoading ? <ActivityIndicator color={colors.brand} style={{ marginTop: space.xl }} /> : q.isError ? (
    <Card style={{ gap: space.sm }} testID="rent-error"><Text style={[s.muted, { color: colors.error }]}>{(q.error as Error).message}</Text></Card>
  ) : d ? (
    <>
      <Card style={{ gap: space.md }} testID="rent-summary">
        <Text style={s.label}>{d.local.name} · {BEDS.find((b) => b.k === beds)?.l ?? "All homes"} · {d.local.month}</Text>
        <Text style={s.big} testID="rent-average">{gbp(rent)}<Text style={s.per}> /month</Text></Text>
        <View style={s.cells}>
          <Cell v={d.local.annual_change != null ? `${d.local.annual_change > 0 ? "+" : ""}${d.local.annual_change}%` : "–"} l="vs last year" />
          <Cell v={vs(rent, d.region?.prices[beds] ?? d.region?.prices.all)} l={`vs ${d.region?.name ?? "region"}`} />
          <Cell v={vs(rent, d.uk?.prices[beds] ?? d.uk?.prices.all)} l="vs UK" />
        </View>
      </Card>
      <Card style={{ gap: space.sm }} testID="rent-breakdown">
        <Text style={s.section}>Average rent by size and type</Text>
        {[...BEDS, ...TYPES].map((x) => (
          <Pressable key={x.k} onPress={() => BEDS.some((b) => b.k === x.k) && setBeds(x.k)} style={s.row}>
            <Text style={s.rowLabel}>{x.l}</Text>
            <Text style={s.rowVal}>{d.local.prices[x.k] ? gbp(d.local.prices[x.k]!) : "–"}</Text>
            <Text style={[s.muted, { width: 70, textAlign: "right" }]}>{d.region?.prices[x.k] ? gbp(d.region.prices[x.k]!) : "–"}</Text>
          </Pressable>
        ))}
        <Text style={s.muted}>Right column: {d.region?.name ?? "region"} average.</Text>
      </Card>
      <Card style={{ gap: space.sm }} testID="rent-yield">
        <Text style={s.section}>Gross yield at this rent</Text>
        <Field label="Property value (£)" value={val} onChangeText={setValue} keyboardType="number-pad" placeholder="e.g. 180000" testID="rent-value-input" />
        <Text style={[s.big, { fontSize: 24, color: colors.brand }]} testID="rent-yield-value">{yieldPct ? `${yieldPct.toFixed(1)}%` : "–"}</Text>
        <Text style={s.muted}>{gbp(rent * 12)} a year ÷ value.{!value && p?.estimated_valuation ? " Value taken from your project." : ""}</Text>
      </Card>
      <Text style={s.muted}>{d.source}</Text>
    </>
  ) : null;

  return (
    <View style={s.root} testID="rent-comps-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="rent-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>Rent comparables</Text>
        <View style={{ width: 44 }} />
      </View>
      <ScrollView contentContainerStyle={[{ padding: wide ? space.xl : space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }, wide && { width: "100%", maxWidth: 1100, alignSelf: "center" }]} keyboardShouldPersistTaps="handled">
        {wide ? (
          <View style={{ flexDirection: "row", gap: space.xl, alignItems: "flex-start" }}>
            <View style={{ width: 400, gap: space.lg }}>{left}</View>
            <View style={{ flex: 1, gap: space.lg }}>{body}</View>
          </View>
        ) : <>{left}{body}</>}
      </ScrollView>
    </View>
  );
}

function Cell({ v, l }: { v: string; l: string }) {
  const s = useStyles();
  return <View style={s.cell}><Text style={s.cellVal}>{v}</Text><Text style={s.muted} numberOfLines={1}>{l}</Text></View>;
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  big: { fontFamily: fonts.extrabold, fontSize: 32, color: c.onSurface, letterSpacing: -0.8 },
  per: { fontFamily: fonts.medium, fontSize: 15, color: c.muted },
  section: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", minHeight: 40, borderTopWidth: 1, borderTopColor: c.divider, gap: space.md },
  rowLabel: { flex: 1, fontFamily: fonts.medium, fontSize: 14, color: c.onSurface },
  rowVal: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
}));
