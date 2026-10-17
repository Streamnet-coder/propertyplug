import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Button, Chip, fonts, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Row = { co_owner_id: string | null; name: string; email: string; is_owner: boolean; pct: number; rent_received: number; expenses: number; net: number };
type Statement = { tax_year: number; label: string; rent_received: number; expenses: number; net: number; rows: Row[]; has_split: boolean; last_sent_at: string | null };

/** Start year of the most recently ended UK tax year (6 April – 5 April). */
function lastTaxYear() {
  const t = new Date();
  const afterApr6 = t.getMonth() > 3 || (t.getMonth() === 3 && t.getDate() >= 6);
  return t.getFullYear() - (afterApr6 ? 1 : 2);
}

/** Pick a tax year, preview each co-owner's share and email their statements. Sent automatically every 6 April too. */
export function StatementsPanel() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const last = lastTaxYear();
  const years = [last + 1, last, last - 1];
  const [ty, setTy] = useState(last);
  const q = useQuery({ queryKey: ["statements", ty], queryFn: () => api<Statement>(`/project/statements?tax_year=${ty}`) });
  const send = useMutation({
    mutationFn: () => api<{ sent: string[]; failed: string[] }>("/project/statements", { body: { tax_year: ty } }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["statements"] });
      toast(r.failed.length ? `Sent to ${r.sent.length}, ${r.failed.length} failed` : `Statements emailed to ${r.sent.length} co-owner${r.sent.length === 1 ? "" : "s"}`, r.failed.length ? "info" : "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const d = q.data;

  return (
    <View style={s.box} testID="statements-panel">
      <Text style={s.title}>Yearly co-owner statements</Text>
      <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
        {years.map((y) => (
          <Chip key={y} label={`${y}/${String(y + 1).slice(2)}${y > last ? " (so far)" : ""}`} selected={ty === y} onPress={() => setTy(y)} testID={`statements-year-${y}`} />
        ))}
      </View>
      {!d ? <ActivityIndicator color={colors.brand} /> : (
        <View style={{ gap: 4 }} testID="statements-preview">
          <Text style={s.muted}>{d.label} · rent {gbp(d.rent_received)} · expenses {gbp(d.expenses)} · net {gbp(d.net)}</Text>
          {d.rows.filter((r) => !r.is_owner && r.pct > 0).map((r) => (
            <Text key={r.co_owner_id} style={s.line} testID={`statements-row-${r.co_owner_id}`}>{r.name} ({r.pct}%): net {gbp(r.net)}</Text>
          ))}
          {d.last_sent_at && <Text style={s.muted} testID="statements-last-sent">Last sent {d.last_sent_at.slice(0, 10)}</Text>}
        </View>
      )}
      <Button small icon="mail" title="Email statements" loading={send.isPending} onPress={() => send.mutate()} testID="statements-send" />
      <Text style={s.muted}>Each co-owner gets their share of rent, expenses, net income, profit and what they put in. You get a copy. Sent automatically every 6 April for the tax year just ended.</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  box: { gap: space.sm, borderTopWidth: 1, borderTopColor: c.border, paddingTop: space.md },
  title: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  line: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
