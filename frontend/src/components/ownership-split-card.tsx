import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Button, Card, fonts, Icon, radius, SectionTitle, space } from "@/src/components/ui";
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
  const [removing, setRemoving] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (cid: string) => api(`/co-owners/${cid}`, { method: "DELETE" }),
    onSuccess: async () => {
      setRemoving(null);
      setDraft(null);
      await Promise.all(["split", "co-owners", "payouts", "statements", "ownership-portfolio"].map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
      toast("Co-owner removed");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const d = q.data;
  if (d && !d.can_edit) {
    const me = d.rows[0]; // co-owner view: only their own share is shared with them
    if (!me || (!me.pct && !me.contribution)) return null;
    return (
      <View>
        <SectionTitle title="Your ownership" />
        <Card style={{ gap: space.sm }} testID="split-mine-card">
          <View style={s.row}>
            <Text style={[s.name, { flex: 1 }]}>Your share</Text>
            <Text style={s.val} testID="split-mine-pct">{me.pct}%</Text>
          </View>
          {d.figures.profit !== null && <View style={s.row}><Text style={[s.muted, { flex: 1 }]}>Your profit share</Text><Text style={s.val}>{gbp(me.profit ?? 0)}</Text></View>}
          <View style={s.row}><Text style={[s.muted, { flex: 1 }]}>Your cashflow / mo</Text><Text style={s.val}>{gbp(me.monthly_cashflow)}</Text></View>
          {me.contribution > 0 && <View style={s.row}><Text style={[s.muted, { flex: 1 }]}>You put in</Text><Text style={s.val}>{gbp(me.contribution)}</Text></View>}
          <Text style={s.muted}>Other owners&apos; shares are private.</Text>
        </Card>
      </View>
    );
  }
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
          {d.can_edit && <View style={s.bin} />}
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
                {d.can_edit && (r.is_owner ? <View style={s.bin} /> : (
                  <Pressable onPress={() => setRemoving(removing === k ? null : k)} hitSlop={6} style={[s.bin, s.binOn]} accessibilityLabel={`Remove ${r.name}`} testID={`split-remove-${k}`}>
                    <Icon name="trash-2" size={16} color={colors.error} />
                  </Pressable>
                ))}
              </View>
              {removing === k && (
                <View style={s.confirm} testID={`split-remove-confirm-box-${k}`}>
                  <Text style={[s.muted, { color: colors.error }]}>Remove {r.name}? They lose access to every project you shared with them and their shares are cleared.</Text>
                  <View style={{ flexDirection: "row", gap: space.sm }}>
                    <Button small variant="outline" title="Cancel" onPress={() => setRemoving(null)} style={{ flex: 1 }} testID={`split-remove-cancel-${k}`} />
                    <Button small variant="danger" title="Remove access" loading={remove.isPending} onPress={() => remove.mutate(k)} style={{ flex: 1 }} testID={`split-remove-confirm-${k}`} />
                  </View>
                </View>
              )}
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
  bin: { width: 36, height: 36, marginLeft: space.xs },
  binOn: { borderRadius: 18, backgroundColor: c.errorTint, alignItems: "center", justifyContent: "center" },
  confirm: { gap: space.sm, backgroundColor: c.errorTint, borderRadius: radius.md, padding: space.md },
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
