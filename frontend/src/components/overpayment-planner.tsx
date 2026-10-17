import Slider from "@react-native-community/slider";
import { useMemo, useState } from "react";
import { Text, View } from "react-native";

import { gbp, Project } from "@/src/api";
import { Card, Field, fonts, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Sim = { months: number; interest: number; balance: number };

/** Month-by-month amortisation with an extra monthly overpayment and an optional one-off lump sum in month 1. */
function simulate(loan: number, rate: number, years: number, repayment: boolean, extra: number, lump: number): Sim {
  const r = rate / 100 / 12;
  const n = Math.max(1, years) * 12;
  const pay = repayment ? (r === 0 ? loan / n : (loan * r) / (1 - Math.pow(1 + r, -n))) : loan * r;
  let bal = Math.max(0, loan - lump);
  let interest = 0;
  let m = 0;
  while (bal > 0.005 && m < n) {
    const i = bal * r;
    interest += i;
    bal = Math.max(0, bal + i - (pay + extra));
    m += 1;
  }
  return { months: m, interest, balance: bal };
}

const yrs = (m: number) => `${Math.floor(m / 12)}y ${m % 12}m`;

export function OverpaymentPlanner({ p }: { p: Project }) {
  const s = useStyles();
  const { colors } = useTheme();
  const loan = p.home_finance.loan;
  const [extra, setExtra] = useState(100);
  const [lump, setLump] = useState("");
  const max = Math.max(500, Math.round(p.home_finance.monthly_payment / 50) * 50);
  const repayment = p.mortgage_type === "repayment";

  const { base, plan } = useMemo(() => {
    const l = Math.min(loan, Number(lump) || 0);
    return { base: simulate(loan, p.mortgage_rate, p.mortgage_term, repayment, 0, 0), plan: simulate(loan, p.mortgage_rate, p.mortgage_term, repayment, extra, l) };
  }, [loan, p.mortgage_rate, p.mortgage_term, repayment, extra, lump]);

  if (!loan) return null;
  const saved = base.interest - plan.interest;
  const cut = base.months - plan.months;
  return (
    <Card style={{ gap: space.md }} testID="overpayment-planner">
      <Text style={s.title}>Overpayment planner</Text>
      <View style={s.rowBetween}>
        <Text style={s.label}>Extra each month</Text>
        <Text style={[s.val, { color: colors.brand }]} testID="overpay-monthly-value">{gbp(extra)}</Text>
      </View>
      <Slider
        testID="overpay-slider"
        minimumValue={0}
        maximumValue={max}
        step={25}
        value={extra}
        onValueChange={setExtra}
        minimumTrackTintColor={colors.brand}
        maximumTrackTintColor={colors.border}
        thumbTintColor={colors.brand}
        style={{ height: 40 }}
      />
      <Field label="One-off lump sum (optional)" value={lump} onChangeText={setLump} keyboardType="decimal-pad" placeholder="0" testID="overpay-lump-input" />
      <View style={s.row}>
        <View style={[s.cell, { backgroundColor: colors.brandTertiary }]}>
          <Text style={[s.big, { color: colors.success }]} testID="overpay-interest-saved">{gbp(Math.max(0, saved))}</Text>
          <Text style={s.muted}>interest saved</Text>
        </View>
        <View style={[s.cell, { backgroundColor: colors.brandTertiary }]}>
          <Text style={[s.big, { color: colors.brand }]} testID="overpay-term-cut">{repayment ? yrs(Math.max(0, cut)) : gbp(loan - plan.balance)}</Text>
          <Text style={s.muted}>{repayment ? "off your term" : "balance cleared"}</Text>
        </View>
      </View>
      <Text style={s.muted} testID="overpay-summary">
        {repayment
          ? `Mortgage-free in ${yrs(plan.months)} instead of ${yrs(base.months)}. Total interest ${gbp(plan.interest)} vs ${gbp(base.interest)}.`
          : plan.balance <= 0.005
            ? `Overpaying clears your interest-only mortgage in ${yrs(plan.months)}, saving ${gbp(Math.max(0, saved))} in interest.`
            : `Interest-only: overpaying leaves ${gbp(plan.balance)} to repay at the end instead of ${gbp(loan)}.`}
      </Text>
      <Text style={s.hint}>Many lenders allow up to 10% of the balance in overpayments a year without charges. Check your deal.</Text>
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  row: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, borderRadius: radius.md, padding: space.md, gap: 2 },
  label: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceTertiary },
  val: { fontFamily: fonts.bold, fontSize: 16 },
  big: { fontFamily: fonts.extrabold, fontSize: 20 },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  hint: { fontFamily: fonts.regular, fontSize: 11, color: c.muted, fontStyle: "italic" },
}));
