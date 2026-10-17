import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Button, Field, fonts, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Payout = { id: string; amount: number; date: string; note: string };
type Person = { co_owner_id: string; name: string; pct: number; earned: number; paid: number; balance: number; payouts: Payout[] };
type Ledger = { income: { rent_received: number; expenses: number; net: number }; people: Person[]; total_owed: number };

/** Owner: each co-owner's share of net rental income to date, what's been paid out, and the balance still owed. */
export function PayoutsPanel() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["payouts"], queryFn: () => api<Ledger>("/project/payouts") });
  const [form, setForm] = useState<{ id: string; amount: string; date: string; note: string } | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const done = (d: Ledger, msg: string) => { queryClient.setQueryData(["payouts"], d); toast(msg); };
  const add = useMutation({
    mutationFn: () => api<Ledger>("/project/payouts", { body: { co_owner_id: form!.id, amount: Number(form!.amount.replace(/[,£\s]/g, "")), date: form!.date.trim(), note: form!.note } }),
    onSuccess: (d) => { setForm(null); done(d, "Payout recorded"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const del = useMutation({
    mutationFn: (id: string) => api<Ledger>(`/project/payouts/${id}`, { method: "DELETE" }),
    onSuccess: (d) => done(d, "Payout removed"),
  });
  const d = q.data;
  if (!d?.people.length) return null;
  const amt = form ? Number(form.amount.replace(/[,£\s]/g, "")) : 0;
  const valid = form && amt > 0 && /^\d{4}-\d{2}-\d{2}$/.test(form.date.trim());

  return (
    <View style={s.box} testID="payouts-panel">
      <Text style={s.title}>Payouts</Text>
      <Text style={s.muted}>Net rental income to date {gbp(d.income.net)} (rent {gbp(d.income.rent_received)} minus expenses {gbp(d.income.expenses)}).</Text>
      {d.people.map((p) => (
        <View key={p.co_owner_id} style={{ gap: 6 }} testID={`payout-person-${p.co_owner_id}`}>
          <View style={s.row}>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{p.name} · {p.pct}%</Text>
              <Text style={s.muted}>Earned {gbp(p.earned)} · paid {gbp(p.paid)}</Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={[s.bal, { color: p.balance > 0 ? colors.brandPrimary : p.balance < 0 ? colors.error : colors.success }]} testID={`payout-balance-${p.co_owner_id}`}>
                {p.balance > 0 ? `Owed ${gbp(p.balance)}` : p.balance < 0 ? `Overpaid ${gbp(-p.balance)}` : "All square"}
              </Text>
              {p.payouts.length > 0 && (
                <Pressable onPress={() => { tap(); setOpenId(openId === p.co_owner_id ? null : p.co_owner_id); }} hitSlop={8} testID={`payout-history-${p.co_owner_id}`}>
                  <Text style={[s.muted, { color: colors.brand }]}>{openId === p.co_owner_id ? "Hide" : `${p.payouts.length} payout${p.payouts.length === 1 ? "" : "s"}`}</Text>
                </Pressable>
              )}
            </View>
          </View>
          {openId === p.co_owner_id && p.payouts.map((x) => (
            <View key={x.id} style={s.pay} testID={`payout-${x.id}`}>
              <Text style={[s.line, { flex: 1 }]}>{x.date} · {gbp(x.amount, 2)}{x.note ? ` · ${x.note}` : ""}</Text>
              <Pressable onPress={() => del.mutate(x.id)} hitSlop={8} testID={`payout-delete-${x.id}`}><Text style={[s.muted, { color: colors.error }]}>Remove</Text></Pressable>
            </View>
          ))}
          {form?.id === p.co_owner_id ? (
            <View style={{ gap: space.sm }}>
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <View style={{ flex: 1 }}><Field label="Amount" value={form.amount} onChangeText={(t) => setForm({ ...form, amount: t })} keyboardType="decimal-pad" placeholder={p.balance > 0 ? String(p.balance) : "0"} testID="payout-amount" /></View>
                <View style={{ flex: 1 }}><Field label="Date" value={form.date} onChangeText={(t) => setForm({ ...form, date: t })} placeholder="YYYY-MM-DD" testID="payout-date" /></View>
              </View>
              <Field label="Note (optional)" value={form.note} onChangeText={(t) => setForm({ ...form, note: t })} placeholder="e.g. Bank transfer, Q3 rent" testID="payout-note" />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" title="Cancel" onPress={() => setForm(null)} style={{ flex: 1 }} testID="payout-cancel" />
                <Button small title="Save payout" disabled={!valid} loading={add.isPending} onPress={() => add.mutate()} style={{ flex: 1 }} testID="payout-save" />
              </View>
            </View>
          ) : (
            <Button small variant="ghost" icon="banknote" title="Record payout" onPress={() => setForm({ id: p.co_owner_id, amount: p.balance > 0 ? String(p.balance) : "", date: new Date().toISOString().slice(0, 10), note: "" })} testID={`payout-add-${p.co_owner_id}`} />
          )}
        </View>
      ))}
      <Text style={s.muted}>Earned uses each person&apos;s current share of all rent received minus property expenses.</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  box: { gap: space.sm, borderTopWidth: 1, borderTopColor: c.border, paddingTop: space.md },
  title: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  row: { flexDirection: "row", gap: space.sm, alignItems: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  bal: { fontFamily: fonts.bold, fontSize: 14 },
  pay: { flexDirection: "row", gap: space.sm, alignItems: "center", backgroundColor: c.surfaceTertiary, borderRadius: radius.sm, padding: space.sm },
  line: { fontFamily: fonts.medium, fontSize: 12, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
