import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, FloorAreas, gbp, ProjectEpc, SoldPrices } from "@/src/api";
import { PortfolioMapView } from "@/src/components/portfolio-map-view";
import { soldMapHtml } from "@/src/components/sold-map-html";
import { Button, Card, Chip, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useLayout } from "@/src/layout";
import { useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const PC_RE = /\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b/i;
const MILES = [{ v: "0.25", l: "¼ mile" }, { v: "0.5", l: "½ mile" }, { v: "1", l: "1 mile" }, { v: "2", l: "2 miles" }, { v: "3", l: "3 miles" }, { v: "5", l: "5 miles" }] as const;
const YEARS = ["1", "2", "3", "5"] as const;
const PAGE = 40;
const fmtDist = (m: number) => (m < 1609 ? `${Math.round(m / 1609.34 * 100) / 100} mi` : `${(m / 1609.34).toFixed(1)} mi`);

export default function SoldMap() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useLayout();
  const { data: p } = useProject();
  const projectPc = p?.address.match(PC_RE)?.[1]?.toUpperCase() ?? "";
  const [input, setInput] = useState<string | null>(null);
  const [postcode, setPostcode] = useState<string | null>(null);
  const [miles, setMiles] = useState<(typeof MILES)[number]["v"]>("0.25");
  const [years, setYears] = useState<(typeof YEARS)[number]>("3");
  const [type, setType] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const pc = postcode ?? projectPc;
  const q = useQuery({
    queryKey: ["sold-prices", pc, miles, years],
    queryFn: () => api<SoldPrices>(`/sold-prices?postcode=${encodeURIComponent(pc)}&miles=${miles}&years=${years}`),
    enabled: !!pc,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });
  const d = q.data;
  const sales = useMemo(() => (d ? d.sales.filter((x) => !type || x.type === type) : []), [d, type]);
  const html = useMemo(() => (d ? soldMapHtml(d, sales, { brand: colors.brand, low: colors.success, high: colors.brandPrimary, centre: colors.onSurface }) : ""), [d, sales, colors]);
  const visible = useMemo(() => sales.slice(0, shown), [sales, shown]);
  const fa = useQuery({
    queryKey: ["floor-areas", d?.postcode, miles, years, type, shown],
    queryFn: () => api<FloorAreas>("/sold-prices/floor-areas", { body: { sales: visible.slice(-PAGE).map((x) => ({ postcode: x.postcode, address: x.address || x.postcode, price: x.price })) } }),
    enabled: visible.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  // Each page is looked up separately; merge pages so earlier rows keep their figures.
  const [areas, setAreas] = useState<Record<string, FloorAreas["items"][number]>>({});
  const rowKey = (x: SoldPrices["sales"][number]) => `${x.postcode}|${x.address}|${x.date}|${x.price}`;
  if (fa.data && visible.length) {
    const page = visible.slice(-PAGE);
    const k0 = rowKey(page[0]);
    if (!(k0 in areas)) setAreas({ ...areas, ...Object.fromEntries(page.map((x, i) => [rowKey(x), fa.data!.items[i]])) });
  }
  const ppsfAll = visible.map((x) => areas[rowKey(x)]?.price_per_sqft).filter((v): v is number => !!v).sort((a, b) => a - b);
  const medianPpsf = ppsfAll.length ? ppsfAll[Math.floor(ppsfAll.length / 2)] : null;
  const typeStats = type && d ? d.stats.by_type[type] : null;
  const epc = useQuery({ queryKey: ["project-epc"], queryFn: () => api<ProjectEpc>("/project/epc"), retry: false, staleTime: 60 * 60 * 1000 });
  const [sizeIn, setSizeIn] = useState<string | null>(null);
  const size = sizeIn ?? (epc.data?.sqft ? String(epc.data.sqft) : "");
  const sizeVal = medianPpsf && Number(size) > 0 ? Math.round((Number(size) * medianPpsf) / 1000) * 1000 : 0;
  const median = typeStats ? typeStats.median : d?.stats.median ?? 0;
  const gdv = p?.estimated_valuation ?? 0;
  const search = () => { tap(); const v = (input ?? pc).trim().toUpperCase(); if (v) { setPostcode(v); setShown(PAGE); } };

  const controls = (
    <Card style={{ gap: space.md }} testID="sold-controls">
      <View style={{ flexDirection: "row", gap: space.sm, alignItems: "flex-end" }}>
        <View style={{ flex: 1 }}>
          <Field label="Postcode" value={input ?? pc} onChangeText={setInput} autoCapitalize="characters" placeholder="e.g. NG7 1AA" selectTextOnFocus maxLength={8} onSubmitEditing={search} returnKeyType="search" testID="sold-postcode-input" />
        </View>
        <Button title="Search" icon="search" onPress={search} testID="sold-search-button" />
      </View>
      <Text style={s.label}>Distance</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        {MILES.map((m) => <Chip key={m.v} label={m.l} selected={miles === m.v} onPress={() => { setMiles(m.v); setShown(PAGE); }} testID={`sold-miles-${m.v}`} />)}
      </ScrollView>
      <Text style={s.label}>Sold in the last</Text>
      <View style={s.chips}>
        {YEARS.map((y) => <Chip key={y} label={`${y} yr${y === "1" ? "" : "s"}`} selected={years === y} onPress={() => { setYears(y); setShown(PAGE); }} testID={`sold-years-${y}`} />)}
      </View>
    </Card>
  );

  const stats = d && (
    <Card style={{ gap: space.md }} testID="sold-stats">
      <Text style={s.label}>{type ?? "All types"} · within {MILES.find((m) => m.v === miles)!.l} of {d.postcode}</Text>
      <View style={s.cells}>
        <Stat v={gbp(median)} l="median sold" id="sold-median" />
        <Stat v={gbp(typeStats ? typeStats.avg : d.stats.avg)} l="average" id="sold-avg" />
        <Stat v={String(typeStats ? typeStats.count : d.stats.count)} l="sales" id="sold-count" />
      </View>
      {medianPpsf && (
        <Text style={s.muted} testID="sold-ppsf-median">
          <Text style={{ fontFamily: fonts.bold, color: colors.brand }}>£{medianPpsf.toLocaleString()} per sq ft</Text> median across {ppsfAll.length} sales shown with an EPC floor area.
        </Text>
      )}
      {medianPpsf && (
        <View style={s.sizeBox} testID="sold-size-valuation">
          <Text style={s.label}>Value by size</Text>
          <View style={{ flexDirection: "row", gap: space.sm, alignItems: "flex-end" }}>
            <View style={{ flex: 1 }}>
              <Field label="Your floor area (sq ft)" value={size} onChangeText={setSizeIn} keyboardType="number-pad" placeholder="e.g. 950" maxLength={6} testID="sold-size-input" />
            </View>
            <View style={{ flex: 1, paddingBottom: space.sm }}>
              <Text style={s.muted}>At £{medianPpsf.toLocaleString()}/sq ft</Text>
              <Text style={[s.cellVal, { color: colors.brand }]} testID="sold-size-value">{sizeVal ? gbp(sizeVal) : "–"}</Text>
            </View>
          </View>
          <Text style={s.muted}>{!sizeIn && epc.data?.sqft ? "Floor area taken from your property's EPC. " : ""}1 m² = 10.76 sq ft.</Text>
          {sizeVal > 0 && <Button small icon="calculator" title={`Use ${gbp(sizeVal)} as BRRR valuation`} onPress={() => router.push({ pathname: "/brrr", params: { valuation: String(sizeVal) } })} testID="sold-use-size-gdv" />}
        </View>
      )}
      {median > 0 && (
        <Button small variant="secondary" icon="calculator" title={`Use ${gbp(median)} as BRRR valuation`} onPress={() => router.push({ pathname: "/brrr", params: { valuation: String(median) } })} testID="sold-use-gdv" />
      )}
      {gdv > 0 && median > 0 && (
        <Text style={[s.muted, { color: gdv > median * 1.15 ? colors.brandPrimary : colors.brand }]} testID="sold-gdv-compare">
          Your valuation {gbp(gdv)} is {Math.abs(Math.round((gdv / median - 1) * 100))}% {gdv >= median ? "above" : "below"} the local median{type ? ` for ${type.toLowerCase()} homes` : ""}.
        </Text>
      )}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        <Chip label="All" selected={!type} onPress={() => { setType(null); setShown(PAGE); }} testID="sold-type-all" />
        {Object.entries(d.stats.by_type).map(([t, v]) => (
          <Chip key={t} label={`${t} · ${gbp(v.median)}`} selected={type === t} onPress={() => { setType(t); setShown(PAGE); }} testID={`sold-type-${t}`} />
        ))}
      </ScrollView>
      <Text style={s.muted}>
        {d.truncated ? `Map shows the ${d.sales.length.toLocaleString()} most recent sales; figures use all ${d.stats.count.toLocaleString()}. ` : ""}
        Median and average exclude &quot;Other&quot; (commercial and bulk) sales.
      </Text>
    </Card>
  );

  const list = d && (
    <View style={{ gap: space.sm }} testID="sold-list">
      <Text style={s.section}>Recent sales ({sales.length.toLocaleString()})</Text>
      {visible.map((x, i) => (
        (() => { const a = areas[rowKey(x)]; return (
        <View key={`${x.postcode}-${x.address}-${x.date}-${i}`} style={s.sale} testID={`sold-sale-${i}`}>
          <View style={{ flex: 1 }}>
            <Text style={s.addr} numberOfLines={1}>{x.address || x.postcode}</Text>
            <Text style={s.muted} numberOfLines={1}>{x.postcode} · {x.type}{x.tenure ? ` · ${x.tenure}` : ""}{x.new_build ? " · New build" : ""} · {fmtDist(x.distance_m)}</Text>
            {a?.sqft ? (
              <Text style={[s.muted, { color: colors.brand, fontFamily: fonts.semibold }]} testID={`sold-ppsf-${i}`}>£{a.price_per_sqft?.toLocaleString()}/sq ft · {a.sqft.toLocaleString()} sq ft{a.epc_band ? ` · EPC ${a.epc_band}` : ""}</Text>
            ) : a ? <Text style={s.muted}>No EPC floor area found</Text> : fa.isFetching ? <Text style={s.muted}>Checking floor area…</Text> : null}
          </View>
          <View style={{ alignItems: "flex-end" }}>
            <Text style={s.price}>{gbp(x.price)}</Text>
            <Text style={s.muted}>{new Date(x.date).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</Text>
          </View>
        </View>
        ); })()
      ))}
      {shown < sales.length && <Button small variant="outline" title={`Show more (${sales.length - shown} left)`} onPress={() => setShown(shown + PAGE)} testID="sold-show-more" />}
      <Text style={s.muted}>{d.source}</Text>
    </View>
  );

  const body = !pc ? (
    <Card style={{ alignItems: "center", gap: space.sm }} testID="sold-no-postcode"><Icon name="map-pin" size={28} color={colors.brand} /><Text style={s.muted}>Enter a postcode in England or Wales to see sold prices around it.</Text></Card>
  ) : q.isLoading ? (
    <View style={s.loading} testID="sold-loading"><ActivityIndicator color={colors.brand} /><Text style={s.muted}>Fetching Land Registry sales{Number(miles) >= 2 ? ", wider areas can take 10-20 seconds" : ""}…</Text></View>
  ) : q.isError ? (
    <Card style={{ gap: space.sm }} testID="sold-error"><Text style={[s.muted, { color: colors.error }]}>{(q.error as Error).message}</Text><Button small title="Try again" onPress={() => q.refetch()} testID="sold-retry" /></Card>
  ) : d && !d.sales.length ? (
    <Card testID="sold-empty"><Text style={s.muted}>No sales recorded within this distance and period. Try a wider distance or longer period.</Text></Card>
  ) : null;

  const map = d && d.sales.length > 0 && (
    <View style={[s.map, wide && { height: undefined, flex: 1, minHeight: 560 }]} testID="sold-map"><PortfolioMapView html={html} /></View>
  );

  return (
    <View style={s.root} testID="sold-map-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="sold-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>Sold prices map</Text>
        <View style={{ width: 44 }} />
      </View>
      <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={[{ padding: wide ? space.xl : space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }, wide && s.contained]}>
        {wide ? (
          <View style={s.cols}>
            <View style={{ flex: 1.4, gap: space.lg }}>{controls}{body}{map}</View>
            <View style={{ flex: 1, gap: space.lg }}>{stats}{list}</View>
          </View>
        ) : (
          <>{controls}{body}{map}{stats}{list}</>
        )}
      </KeyboardAwareScrollView>
    </View>
  );
}

function Stat({ v, l, id }: { v: string; l: string; id: string }) {
  const s = useStyles();
  return <View style={s.cell}><Text style={s.cellVal} numberOfLines={1} testID={id}>{v}</Text><Text style={s.muted}>{l}</Text></View>;
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  contained: { width: "100%", maxWidth: 1280, alignSelf: "center" },
  cols: { flexDirection: "row", gap: space.xl, alignItems: "flex-start" },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  chips: { flexDirection: "row", gap: space.sm, flexWrap: "wrap" },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  loading: { alignItems: "center", gap: space.sm, padding: space.xl },
  map: { height: 380, borderRadius: radius.lg, overflow: "hidden", borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceTertiary },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  sizeBox: { gap: space.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md },
  sale: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  addr: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  price: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
}));
