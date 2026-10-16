import { useState } from "react";
import { Text, View } from "react-native";
import Svg, { Circle, Line, Path, Rect } from "react-native-svg";

import { Category, gbp, LineItem, SpendTrend } from "@/src/api";
import { fonts, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const H = 150;
const PAD = 8;
const CATS: Category[] = ["Hard Cost", "Soft Cost", "Contingency"];

const shortDate = (d: string) => new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export function SpendTrendChart({ trend }: { trend: SpendTrend }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [w, setW] = useState(0);
  const pts = trend.points;
  const last = pts[pts.length - 1]?.spent ?? 0;
  const over = trend.budget > 0 && last > trend.budget;
  const max = Math.max(trend.budget, last, 1) * 1.1;
  const y = (v: number) => PAD + (H - PAD * 2) * (1 - v / max);
  const x = (i: number) => (pts.length === 1 ? w / 2 : PAD + ((w - PAD * 2) * i) / (pts.length - 1));
  const lineColor = over ? colors.error : colors.brand;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.spent)}`).join(" ");
  const area = pts.length > 1 ? `${path} L${x(pts.length - 1)},${H - PAD} L${x(0)},${H - PAD} Z` : "";

  return (
    <View style={s.card} testID="spend-trend-chart">
      <View style={s.head}>
        <Text style={s.title}>Spend vs budget</Text>
        <Text style={[s.badge, { color: over ? colors.error : colors.success }]} testID="spend-trend-status">
          {trend.budget > 0 ? `${Math.round((last / trend.budget) * 100)}% used` : "No budget set"}
        </Text>
      </View>
      {pts.length === 0 ? (
        <Text style={s.meta} testID="spend-trend-empty">Log actual costs to see your spend build up over time.</Text>
      ) : (
        <>
          <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ height: H }}>
            {w > 0 && (
              <Svg width={w} height={H}>
                {trend.budget > 0 && <Line x1={0} x2={w} y1={y(trend.budget)} y2={y(trend.budget)} stroke={colors.muted} strokeWidth={1.5} strokeDasharray="6 4" />}
                {area ? <Path d={area} fill={lineColor} opacity={0.12} /> : null}
                {pts.length > 1 && <Path d={path} stroke={lineColor} strokeWidth={2.5} fill="none" strokeLinejoin="round" />}
                {pts.length <= 12 && pts.map((p, i) => <Circle key={p.date} cx={x(i)} cy={y(p.spent)} r={3.5} fill={lineColor} />)}
              </Svg>
            )}
          </View>
          <View style={s.axis}>
            <Text style={s.meta}>{shortDate(pts[0].date)}</Text>
            {pts.length > 1 && <Text style={s.meta}>{shortDate(pts[pts.length - 1].date)}</Text>}
          </View>
          {pts.length === 1 && <Text style={s.meta}>Log costs on other days to see your trend line.</Text>}
          <View style={s.legend}>
            <View style={s.legendItem}><View style={[s.swatch, { backgroundColor: lineColor }]} /><Text style={s.meta}>Spent {gbp(last)}</Text></View>
            {trend.budget > 0 && <View style={s.legendItem}><View style={[s.swatch, { backgroundColor: colors.muted, height: 2 }]} /><Text style={s.meta}>Budget {gbp(trend.budget)}</Text></View>}
          </View>
        </>
      )}
    </View>
  );
}

export function CategoryBars({ items }: { items: LineItem[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const rows = CATS.map((c) => {
    const list = items.filter((i) => i.category === c);
    return { c, b: list.reduce((a, i) => a + i.budgeted, 0), sp: list.reduce((a, i) => a + i.spent, 0) };
  }).filter((r) => r.b > 0 || r.sp > 0);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => Math.max(r.b, r.sp)), 1);

  return (
    <View style={s.card} testID="category-bars-chart">
      <Text style={s.title}>By category</Text>
      {rows.map((r) => {
        const over = r.sp > r.b;
        return (
          <View key={r.c} style={{ gap: 4 }} testID={`category-bar-${r.c.replace(" ", "-").toLowerCase()}`}>
            <View style={s.head}>
              <Text style={s.rowLabel}>{r.c}</Text>
              <Text style={[s.meta, over && { color: colors.error }]}>{gbp(r.sp)} / {gbp(r.b)}</Text>
            </View>
            <Svg width="100%" height={10}>
              <Rect x="0" y="0" width={`${(r.b / max) * 100}%`} height={10} rx={5} fill={colors.border} />
              <Rect x="0" y="0" width={`${(r.sp / max) * 100}%`} height={10} rx={5} fill={over ? colors.error : colors.brand} />
            </Svg>
          </View>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  badge: { fontFamily: fonts.semibold, fontSize: 12 },
  rowLabel: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  meta: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  axis: { flexDirection: "row", justifyContent: "space-between", marginTop: -space.sm },
  legend: { flexDirection: "row", gap: space.lg },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  swatch: { width: 12, height: 4, borderRadius: 2 },
}));
