import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Card, fonts, FormScreen, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Person = { key: string; name: string; email: string; is_owner: boolean; projects: number; contribution: number; profit: number; annual_cashflow: number; cash_return_pct: number | null };
type Proj = { project_id: string; project_name: string; rows: { co_owner_id: string | null; name: string; pct: number; contribution: number; profit: number | null; annual_cashflow: number }[] };

/** Owner view: every person's share, cash put in and returns across all properties with an ownership split. */
export default function OwnershipPortfolio() {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["ownership-portfolio"], queryFn: () => api<{ people: Person[]; projects: Proj[] }>("/ownership/portfolio") });
  const d = q.data;

  return (
    <FormScreen title="Ownership across portfolio" testID="ownership-portfolio-screen">
      {q.isLoading ? <ActivityIndicator color={colors.brand} /> : !d?.projects.length ? (
        <Card testID="ownership-portfolio-empty"><Text style={s.muted}>No ownership splits yet. Open a property and use the Ownership split card on its home screen to add shares and what each person put in.</Text></Card>
      ) : (
        <>
          <Text style={s.section}>People</Text>
          {d.people.map((p) => (
            <Card key={p.key} style={{ gap: space.sm }} testID={`ownership-person-${p.key}`}>
              <Text style={s.name}>{p.is_owner ? `${p.name} (you)` : p.name}</Text>
              <Text style={s.muted}>{p.email} · {p.projects} propert{p.projects === 1 ? "y" : "ies"}</Text>
              <View style={s.kpis}>
                <View style={s.kpi}><Text style={s.kv}>{gbp(p.contribution)}</Text><Text style={s.muted}>put in</Text></View>
                <View style={s.kpi}><Text style={s.kv}>{gbp(p.profit)}</Text><Text style={s.muted}>profit share</Text></View>
                <View style={s.kpi}><Text style={[s.kv, { color: p.annual_cashflow < 0 ? colors.error : colors.success }]}>{gbp(p.annual_cashflow)}</Text><Text style={s.muted}>cashflow / yr</Text></View>
              </View>
              {p.cash_return_pct !== null && <Text style={s.muted} testID={`ownership-person-return-${p.key}`}>Cash return {p.cash_return_pct}% a year on what they put in</Text>}
            </Card>
          ))}
          <Text style={s.section}>By property</Text>
          {d.projects.map((pr) => (
            <Card key={pr.project_id} style={{ gap: 6 }} testID={`ownership-project-${pr.project_id}`}>
              <Text style={s.name}>{pr.project_name}</Text>
              {pr.rows.map((r) => (
                <View key={r.co_owner_id ?? "owner"} style={s.row}>
                  <Text style={[s.line, { flex: 1 }]} numberOfLines={1}>{r.name}</Text>
                  <Text style={[s.line, s.n]}>{r.pct}%</Text>
                  <Text style={[s.muted, s.n]}>{gbp(r.contribution)} in</Text>
                </View>
              ))}
            </Card>
          ))}
          <Text style={s.muted}>Profit = valuation minus purchase and budget. Cashflow = rent minus mortgage, a year. Totals add properties together, so they assume one currency.</Text>
        </>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  section: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  name: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  kpis: { flexDirection: "row", justifyContent: "space-between", gap: space.sm },
  kpi: { alignItems: "center", flex: 1 },
  kv: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", gap: space.sm, alignItems: "center", minHeight: 28 },
  n: { width: 90, textAlign: "right" },
  line: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
