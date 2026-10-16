import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";

import { api, CURRENCIES, CurrencyCode, gbp } from "@/src/api";
import { Chip, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, usePortfolio } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const CODES = Object.keys(CURRENCIES) as CurrencyCode[];

/** Portfolio totals across all projects, converted to the user's home currency at live rates. */
export function PortfolioCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = usePortfolio();
  const [picking, setPicking] = useState(false);
  const setHome = useMutation({
    mutationFn: (currency: CurrencyCode) => api("/portfolio/home-currency", { method: "PUT", body: { currency } }),
    onSuccess: async () => { setPicking(false); await invalidate("projects"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (q.isLoading) return <View style={[s.card, { alignItems: "center" }]}><ActivityIndicator color={colors.brand} /></View>;
  if (q.isError || !q.data) return <View style={s.card}><Text style={s.muted} testID="portfolio-error">Exchange rates unavailable right now. Pull back later.</Text></View>;
  const d = q.data;
  const h = d.home_currency;
  const t = d.totals;
  const multi = d.by_currency.length > 1 || d.by_currency[0]?.currency !== h;
  const cells = [
    { l: "Purchase", v: t.purchase_price },
    { l: "Valuation", v: t.estimated_valuation },
    { l: "Budget", v: t.total_budget },
    { l: "Spent", v: t.total_spent },
  ];

  return (
    <View style={s.card} testID="portfolio-card">
      <View style={s.row}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Portfolio</Text>
          <Text style={s.muted}>{d.projects} propert{d.projects === 1 ? "y" : "ies"}{d.land_count ? ` · ${d.land_count} land` : ""}</Text>
        </View>
        <Pressable onPress={() => { tap(); setPicking((x) => !x); }} style={s.homeBtn} testID="portfolio-home-currency-button" hitSlop={6}>
          <Text style={s.homeText}>{h}</Text>
          <Icon name={picking ? "chevron-up" : "chevron-down"} size={14} color={colors.brand} />
        </Pressable>
      </View>
      {picking && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {CODES.map((c) => (
            <Chip key={c} label={c} selected={c === h} onPress={() => setHome.mutate(c)} testID={`portfolio-home-${c}`} />
          ))}
        </ScrollView>
      )}
      <View style={s.grid}>
        {cells.map((c) => (
          <View key={c.l} style={s.cell} testID={`portfolio-total-${c.l.toLowerCase()}`}>
            <Text style={s.muted}>{c.l}</Text>
            <Text style={s.val}>{gbp(c.v, 0, h)}</Text>
          </View>
        ))}
      </View>
      {multi && (
        <View style={{ gap: 4 }} testID="portfolio-by-currency">
          {d.by_currency.map((g) => (
            <Text key={g.currency} style={s.muted}>
              {g.currency} · {g.projects} · spent {gbp(g.total_spent, 0, g.currency)}
              {g.currency !== h ? `  (1 ${g.currency} = ${g.rate_to_home.toFixed(g.rate_to_home < 0.01 ? 5 : 3)} ${h})` : ""}
            </Text>
          ))}
        </View>
      )}
      <Text style={s.foot}>{multi ? `Converted to ${h} at live rates · ${d.rate_date}` : `All in ${h}`}{d.stale ? " · cached" : ""}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  foot: { fontFamily: fonts.regular, fontSize: 11, color: c.muted },
  homeBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 36, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.brandTertiary },
  homeText: { fontFamily: fonts.bold, fontSize: 13, color: c.brand },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  cell: { flexBasis: "47%", flexGrow: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  val: { fontFamily: fonts.extrabold, fontSize: 16, color: c.onSurface },
}));
