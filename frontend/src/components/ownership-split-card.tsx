import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Text, TextInput, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Button, Card, fonts, radius, SectionTitle, space } from "@/src/components/ui";
import { StatementsPanel } from "@/src/components/coowner-statements";
import { PayoutsPanel } from "@/src/components/payouts-panel";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export type SplitRow = {
  co_owner_id: string | null; name: string; email: string; pct: number; is_owner: boolean; profit: number | null; monthly_rent: number; monthly_cashflow: number; annual_cashflow: number;
  contribution: number; cash_return_pct: number | null; profit_return_pct: number | null;
};
export type Split = {
  rows: SplitRow[]; figures: { profit: number | null; monthly_rent: number; monthly_cashflow: number; annual_cashflow: number; total_contributed: number };
  can_edit: boolean; has_split: boolean; has_contributions: boolean;
};
type Draft = Record<string, { pct: string; put: string }>;
const key = (r: SplitRow) => r.co_owner_id ?? "owner";
const num = (t: string) => Number((t || "0").replace(/[,£$€\s]/g, ""));

/** Ownership split on the project money summary: each person's %, capital put in, and their share of profit and rent cashflow. */
export function OwnershipSplitCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["split"], queryFn: () => api<Split>("/project/split") });
  const [draft, setDraft] = useState<Draft | null>(null);
  const save = useMutation({
    mutationFn: (b: { shares: Record<string, number>; contributions: Record<string, number> }) => api<Split>("/project/split", { method: "PUT", body: b }),
    onSuccess: (d) => { queryClient.setQueryData(["split"], d); queryClient.invalidateQueries({ queryKey: ["statements"] }); queryClient.invalidateQueries({ queryKey: ["payouts"] }); setDraft(null); toast("Ownership split saved"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const d = q.data;
  if (!d || d.rows.length < 2) return null; // only you on this project

  const others = d.rows.filter((r) => !r.is_owner);
  const pcts = draft ? Object.fromEntries(others.map((r) => [key(r), num(draft[key(r)].pct)])) : null;
  const puts = draft ? Object.fromEntries(d.rows.map((r) => [key(r), num(draft[key(r)].put)])) : null;
  const bad = draft ? [...Object.values(pcts!).map((v) => !Number.isFinite(v) || v < 0 || v > 100), ...Object.values(puts!).map((v) => !Number.isFinite(v) || v < 0)].some(Boolean) : false;
  const ownerPct = pcts ? 100 - Object.values(pcts).reduce((a, v) => a + (Number.isFinite(v) ? v : 0), 0) : d.rows[0].pct;
  const showProfit = d.figures.profit !== null;
  const startEdit = () => setDraft(Object.fromEntries(d.rows.map((r) => [key(r), { pct: r.pct && !r.is_owner ? String(r.pct) : "", put: r.contribution ? String(r.contribution) : "" }])));
  const setD = (k: string, f: "pct" | "put", t: string) => setDraft({ ...draft!, [k]: { ...draft![k], [f]: t } });

  return (
    <View>
      <SectionTitle title="Ownership split" action={d.can_edit && !draft ? "Edit" : undefined} onAction={startEdit} testID="split-edit" />
      <Card style={{ gap: space.md }} testID="split-card">
        {!d.has_split && !draft && <Text style={s.muted} testID="split-empty">You own 100%. Tap Edit to give co-owners a share and record what everyone put in.</Text>}
        <View style={s.headRow}>
          <Text style={[s.th, { flex: 1.6 }]}>Person</Text>
          <Text style={[s.th, s.n]}>Share</Text>
          {showProfit && <Text style={[s.th, s.n]}>Profit</Text>}
          <Text style={[s.th, s.n]}>Cashflow/mo</Text>
        </View>
        {d.rows.map((r) => {
          const k = key(r);
          const pct = r.is_owner ? ownerPct : pcts ? pcts[k] : r.pct;
          const part = (v: number | null) => (v === null ? "–" : gbp((v * (Number.isFinite(pct) ? pct : 0)) / 100));
          return (
            <View key={k} style={{ gap: 4 }} testID={`split-row-${k}`}>
              <View style={s.row}>
                <View style={{ flex: 1.6 }}>
                  <Text style={s.name} numberOfLines={1}>{r.is_owner ? `${r.name} (you)` : r.name}</Text>
                  {!r.is_owner && <Text style={s.muted} numberOfLines={1}>{r.email}</Text>}
                </View>
                {draft && !r.is_owner ? (
                  <View style={[s.n, s.inputWrap]}>
                    <TextInput value={draft[k].pct} onChangeText={(t) => setD(k, "pct", t)} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={colors.muted} style={s.input} testID={`split-input-${k}`} />
                    <Text style={s.muted}>%</Text>
                  </View>
                ) : (
                  <Text style={[s.val, s.n, ownerPct < 0 && r.is_owner && { color: colors.error }]} testID={`split-pct-${k}`}>{Math.round(pct * 100) / 100}%</Text>
                )}
                {showProfit && <Text style={[s.val, s.n]}>{part(d.figures.profit)}</Text>}
                <Text style={[s.val, s.n, { color: d.figures.monthly_cashflow < 0 ? colors.error : colors.onSurface }]}>{part(d.figures.monthly_cashflow)}</Text>
              </View>
              {draft ? (
                <View style={s.putRow}>
                  <Text style={s.muted}>Put in</Text>
                  <TextInput value={draft[k].put} onChangeText={(t) => setD(k, "put", t)} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={colors.muted} style={[s.input, { minWidth: 110 }]} testID={`split-put-${k}`} />
                </View>
              ) : r.contribution > 0 ? (
                <Text style={s.muted} testID={`split-contrib-${k}`}>
                  Put in {gbp(r.contribution)}
                  {r.cash_return_pct !== null ? ` · cash return ${r.cash_return_pct}%/yr` : ""}
                  {r.profit_return_pct !== null ? ` · profit ${r.profit_return_pct}% of cash in` : ""}
                </Text>
              ) : null}
            </View>
          );
        })}
        <Text style={s.muted}>
          {showProfit ? `Profit ${gbp(d.figures.profit!)} = valuation minus purchase and budget. ` : "Add a valuation to see profit. "}
          Cashflow {gbp(d.figures.monthly_cashflow)}/mo = rent minus mortgage.
          {d.has_contributions ? ` Total put in ${gbp(d.figures.total_contributed)}.` : ""}
        </Text>
        {draft && (
          <View style={{ gap: space.sm }}>
            {ownerPct < 0 && <Text style={[s.muted, { color: colors.error }]} testID="split-over">Shares add up to more than 100%.</Text>}
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="outline" title="Cancel" onPress={() => setDraft(null)} style={{ flex: 1 }} testID="split-cancel" />
              <Button small title="Save split" disabled={bad || ownerPct < 0} loading={save.isPending} onPress={() => save.mutate({ shares: pcts!, contributions: puts! })} style={{ flex: 1 }} testID="split-save" />
            </View>
          </View>
        )}
        {d.has_split && d.can_edit && !draft && <StatementsPanel />}
        {d.has_split && d.can_edit && !draft && <PayoutsPanel />}
      </Card>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  headRow: { flexDirection: "row", gap: space.sm, borderBottomWidth: 1, borderBottomColor: c.border, paddingBottom: space.xs },
  th: { fontFamily: fonts.semibold, fontSize: 11, color: c.muted, textTransform: "uppercase" },
  row: { flexDirection: "row", gap: space.sm, alignItems: "center", minHeight: 44 },
  putRow: { flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "flex-end" },
  n: { flex: 1, textAlign: "right" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  val: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  inputWrap: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: 2 },
  input: { minWidth: 52, height: 40, borderWidth: 1, borderColor: c.border, borderRadius: radius.sm, paddingHorizontal: space.sm, textAlign: "right", fontFamily: fonts.medium, color: c.onSurface },
}));
