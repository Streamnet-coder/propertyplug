import { Text, View } from "react-native";

import { CurrencyCode, gbp, MapPin } from "@/src/api";
import { fonts, radius, space } from "@/src/components/ui";
import { usePortfolio } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const KEYS = [
  { k: "purchase_price", l: "Purchase" },
  { k: "estimated_valuation", l: "Value" },
  { k: "total_budget", l: "Budget" },
  { k: "total_spent", l: "Spent" },
] as const;

/** Totals for the pins currently shown on the map: native currency if they share one, else converted to the home currency. */
export function FilterTotals({ pins, filtered }: { pins: MapPin[]; filtered: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const pf = usePortfolio();
  if (!pins.length) return null;
  const curs = [...new Set(pins.map((p) => p.currency))];
  const single = curs.length === 1;
  const home = pf.data?.home_currency;
  const rate = (c: CurrencyCode) => pf.data?.by_currency.find((g) => g.currency === c)?.rate_to_home;
  if (!single && (!home || curs.some((c) => rate(c) == null))) return null; // rates still loading / unavailable
  const out: CurrencyCode = single ? curs[0] : home!;
  const sum = (k: (typeof KEYS)[number]["k"]) => pins.reduce((a, p) => a + p[k] * (single ? 1 : rate(p.currency)!), 0);
  const spent = sum("total_spent");
  const budget = sum("total_budget");

  return (
    <View style={s.bar} testID="map-filter-totals">
      <View style={s.head}>
        <Text style={s.title}>{filtered ? "Filtered totals" : "Portfolio totals"} · {pins.length} propert{pins.length === 1 ? "y" : "ies"}</Text>
        <Text style={[s.tag, budget > 0 && spent > budget && { color: colors.error }]} testID="map-totals-currency">
          {single ? out : `in ${out} at live rates`}
        </Text>
      </View>
      <View style={s.row}>
        {KEYS.map(({ k, l }) => (
          <View key={k} style={s.cell} testID={`map-total-${k}`}>
            <Text style={s.val} numberOfLines={1} adjustsFontSizeToFit>{gbp(sum(k), 0, out)}</Text>
            <Text style={s.lbl}>{l}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  bar: { backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.border, paddingHorizontal: space.lg, paddingVertical: space.sm, gap: 6 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontFamily: fonts.bold, fontSize: 13, color: c.onSurface },
  tag: { fontFamily: fonts.semibold, fontSize: 11, color: c.muted },
  row: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, paddingVertical: 6, paddingHorizontal: 8 },
  val: { fontFamily: fonts.extrabold, fontSize: 14, color: c.onSurface },
  lbl: { fontFamily: fonts.regular, fontSize: 11, color: c.muted },
}));
