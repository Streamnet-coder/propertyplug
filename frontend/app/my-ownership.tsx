import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Card, fonts, FormScreen, Icon, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Stmt = { tax_year: number; sent_at: string; label: string };
type Mine = {
  project_id: string; project_name: string; address: string; owner_name: string; pct: number; contribution: number; profit: number | null;
  monthly_cashflow: number; annual_cashflow: number; cash_return_pct: number | null; profit_return_pct: number | null; statements: Stmt[];
};
type Detail = { label: string; whole: { rent_received: number; expenses: number; net: number }; mine: { pct: number; rent_received: number; expenses: number; net: number; profit: number | null; contribution: number } };

/** Co-owner's own view: their share, cash put in, returns and every statement sent to them, across everyone who shared projects. */
export default function MyOwnership() {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["my-ownership"], queryFn: () => api<{ projects: Mine[]; totals: { contribution: number; profit: number; annual_cashflow: number } }>("/my-ownership") });
  const d = q.data;

  return (
    <FormScreen title="My ownership" testID="my-ownership-screen">
      {q.isLoading ? <ActivityIndicator color={colors.brand} /> : !d?.projects.length ? (
        <Card testID="my-ownership-empty"><Text style={s.muted}>No ownership shares yet. When an owner gives you a share or records what you put in, it shows here with your statements.</Text></Card>
      ) : (
        <>
          <Card style={s.kpis} testID="my-ownership-totals">
            <View style={s.kpi}><Text style={s.kv}>{gbp(d.totals.contribution)}</Text><Text style={s.muted}>put in</Text></View>
            <View style={s.kpi}><Text style={s.kv}>{gbp(d.totals.profit)}</Text><Text style={s.muted}>profit share</Text></View>
            <View style={s.kpi}><Text style={[s.kv, { color: d.totals.annual_cashflow < 0 ? colors.error : colors.success }]}>{gbp(d.totals.annual_cashflow)}</Text><Text style={s.muted}>cashflow / yr</Text></View>
          </Card>
          {d.projects.map((p) => <ProjectCard key={p.project_id} p={p} />)}
        </>
      )}
    </FormScreen>
  );
}

function ProjectCard({ p }: { p: Mine }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [open, setOpen] = useState<{ ty: number; d: Detail } | null>(null);
  const load = useMutation({
    mutationFn: (ty: number) => api<Detail>(`/my-ownership/statement?project_id=${p.project_id}&tax_year=${ty}`).then((d) => ({ ty, d })),
    onSuccess: setOpen,
    onError: (e: Error) => toast(e.message, "error"),
  });
  return (
    <Card style={{ gap: space.sm }} testID={`my-ownership-${p.project_id}`}>
      <Text style={s.name}>{p.project_name}</Text>
      <Text style={s.muted}>{p.address ? `${p.address} · ` : ""}shared by {p.owner_name}</Text>
      <View style={s.grid}>
        <Stat label="Your share" value={`${p.pct}%`} />
        <Stat label="Put in" value={gbp(p.contribution)} />
        <Stat label="Profit share" value={p.profit === null ? "–" : gbp(p.profit)} />
        <Stat label="Cashflow / mo" value={gbp(p.monthly_cashflow)} />
      </View>
      {(p.cash_return_pct !== null || p.profit_return_pct !== null) && (
        <Text style={s.muted} testID={`my-ownership-returns-${p.project_id}`}>
          {p.cash_return_pct !== null ? `Cash return ${p.cash_return_pct}%/yr` : ""}{p.cash_return_pct !== null && p.profit_return_pct !== null ? " · " : ""}
          {p.profit_return_pct !== null ? `profit ${p.profit_return_pct}% of cash in` : ""}
        </Text>
      )}
      <Text style={s.section}>Statements</Text>
      {!p.statements.length && <Text style={s.muted}>None sent yet. They arrive by email every April.</Text>}
      {p.statements.map((st) => (
        <View key={st.tax_year}>
          <Pressable onPress={() => { tap(); open?.ty === st.tax_year ? setOpen(null) : load.mutate(st.tax_year); }} style={s.stmt} testID={`my-statement-${p.project_id}-${st.tax_year}`}>
            <Icon name="file-text" size={16} color={colors.brand} />
            <Text style={[s.line, { flex: 1 }]}>{st.label}</Text>
            <Text style={s.muted}>sent {st.sent_at.slice(0, 10)}</Text>
            {load.isPending && load.variables === st.tax_year ? <ActivityIndicator size="small" color={colors.brand} /> : <Icon name={open?.ty === st.tax_year ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />}
          </Pressable>
          {open?.ty === st.tax_year && (
            <View style={s.detail} testID={`my-statement-detail-${p.project_id}-${st.tax_year}`}>
              <Row k={`Rent received (${open.d.mine.pct}%)`} v={gbp(open.d.mine.rent_received, 2)} />
              <Row k="Property expenses" v={gbp(open.d.mine.expenses, 2)} />
              <Row k="Net income" v={gbp(open.d.mine.net, 2)} bold />
              {open.d.mine.profit !== null && <Row k="Share of estimated profit" v={gbp(open.d.mine.profit, 2)} />}
              {open.d.mine.contribution > 0 && <Row k="Your capital contribution" v={gbp(open.d.mine.contribution, 2)} />}
              <Text style={s.muted}>Whole property: rent {gbp(open.d.whole.rent_received, 2)}, expenses {gbp(open.d.whole.expenses, 2)}, net {gbp(open.d.whole.net, 2)}. Figures shown at today&apos;s shares.</Text>
            </View>
          )}
        </View>
      ))}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const s = useStyles();
  return <View style={s.stat}><Text style={s.line}>{value}</Text><Text style={s.muted}>{label}</Text></View>;
}

function Row({ k, v, bold }: { k: string; v: string; bold?: boolean }) {
  const s = useStyles();
  return <View style={s.row}><Text style={[s.muted, { flex: 1 }]}>{k}</Text><Text style={[s.line, bold && { fontFamily: fonts.bold }]}>{v}</Text></View>;
}

const useStyles = makeStyles((c) => ({
  kpis: { flexDirection: "row", justifyContent: "space-between", gap: space.sm },
  kpi: { alignItems: "center", flex: 1 },
  kv: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  name: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6, marginTop: space.xs },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  stat: { width: "47%", backgroundColor: c.surfaceTertiary, borderRadius: 10, padding: space.sm, gap: 2 },
  stmt: { flexDirection: "row", alignItems: "center", gap: space.sm, minHeight: 44 },
  detail: { gap: 6, backgroundColor: c.surfaceTertiary, borderRadius: 10, padding: space.md },
  row: { flexDirection: "row", gap: space.sm, alignItems: "center" },
  line: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
