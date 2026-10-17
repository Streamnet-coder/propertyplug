import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { gbp, Project } from "@/src/api";
import { OverpaymentPlanner } from "@/src/components/overpayment-planner";
import { Card, fonts, Icon, radius, SectionTitle, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

/** Personal-home mode: mortgage cost, equity before/after the refurb, and remortgaging to pay for it. */
export function HomeFinanceCard({ p }: { p: Project }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const h = p.home_finance;
  const r = h.remortgage;
  const cell = (val: string, lbl: string, testID?: string, color?: string) => (
    <View style={s.cell}><Text style={[s.val, color ? { color } : null]} testID={testID} numberOfLines={1}>{val}</Text><Text style={s.muted}>{lbl}</Text></View>
  );
  return (
    <View style={{ gap: space.md }}>
      <SectionTitle title="Mortgage & equity" action="Edit" onAction={() => router.push("/project-edit")} testID="home-finance-edit" />
      <Card style={{ gap: space.md }} testID="home-finance-card">
        <View style={s.rowBetween}>
          <View>
            <Text style={s.label}>Monthly payment</Text>
            <Text style={[s.big, { color: colors.brand }]} testID="home-monthly-payment">{gbp(h.monthly_payment)}</Text>
          </View>
          <View style={{ alignItems: "flex-end" }}>
            <Text style={s.label}>Equity after refurb</Text>
            <Text style={[s.big, { color: colors.success }]} testID="home-equity-after">{gbp(h.equity_after)}</Text>
          </View>
        </View>
        <View style={s.row}>
          {cell(gbp(h.loan), "mortgage", "home-loan")}
          {cell(`${h.ltv_now.toFixed(0)}% → ${h.ltv_after.toFixed(0)}%`, "LTV now → after", "home-ltv")}
          {cell(gbp(h.equity_now), "equity now", "home-equity-now")}
        </View>
        <View style={s.row}>
          {cell(gbp(h.value_added), "value added", "home-value-added", colors.success)}
          {cell(gbp(h.net_value_added), "after refurb cost", "home-net-value-added", h.net_value_added < 0 ? colors.error : colors.success)}
          {cell(gbp(h.total_interest), "total interest", "home-total-interest")}
        </View>
        <Text style={s.muted}>{p.mortgage_type === "repayment" ? "Repayment" : "Interest-only"} · {p.mortgage_term} years at {p.mortgage_rate}% · {gbp(p.deposit)} deposit</Text>
        {h.fixed_rate_end && (
          <Text style={[s.muted, h.fixed_days_left != null && h.fixed_days_left <= 90 && { color: colors.warning, fontFamily: fonts.semibold }]} testID="home-fixed-rate">
            Fixed rate {h.fixed_days_left != null && h.fixed_days_left < 0 ? `ended ${h.fixed_rate_end}` : `ends ${h.fixed_rate_end} (${h.fixed_days_left} days)`}
          </Text>
        )}
      </Card>
      <OverpaymentPlanner p={p} />
      <Card style={{ gap: space.md }} testID="remortgage-card">
        <Text style={s.title}>Remortgage to fund the refurb</Text>
        <Text style={s.muted}>Borrow against the after-refurb value of {gbp(p.estimated_valuation)} at up to {p.remortgage_ltv}% LTV.</Text>
        <View style={s.row}>
          {cell(gbp(r.borrow_for_refurb), "borrow for refurb", "remortgage-borrow")}
          {cell(gbp(r.new_loan), "new mortgage", "remortgage-new-loan")}
          {cell(`${r.new_ltv.toFixed(0)}%`, "new LTV", "remortgage-new-ltv")}
        </View>
        <View style={s.row}>
          {cell(gbp(r.new_payment), "new monthly", "remortgage-new-payment")}
          {cell(`+${gbp(r.payment_increase)}`, "extra / month", "remortgage-increase", colors.warning)}
          {cell(gbp(r.equity_after), "equity left", "remortgage-equity")}
        </View>
        <View style={[s.banner, { backgroundColor: r.covers_refurb ? colors.brandTertiary : colors.orangeTint }]} testID="remortgage-verdict">
          <Text style={[s.bannerText, { color: r.covers_refurb ? colors.brand : colors.warning }]}>
            {r.covers_refurb ? `Remortgaging could cover the full ${gbp(p.total_budget)} refurb budget.` : `Remortgaging covers ${gbp(r.borrow_for_refurb)}. ${gbp(r.shortfall)} would need to come from savings.`}
          </Text>
        </View>
        {h.scenarios.length > 0 && (
          <View style={{ gap: space.sm }} testID="remortgage-scenarios">
            <Text style={s.title}>Compare deals on {gbp(r.new_loan)}</Text>
            {h.scenarios.map((x, i) => (
              <View key={i} style={[s.scen, x.best_monthly && { borderColor: colors.success, backgroundColor: colors.brandTertiary }]} testID={`scenario-${i}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.val}>{x.label} · {x.rate}%</Text>
                  <Text style={s.muted}>{x.fee ? `${gbp(x.fee)} fee` : "No fee"} · 2-yr cost {gbp(x.two_year_cost)}</Text>
                  <View style={{ flexDirection: "row", gap: 6, marginTop: 4 }}>
                    {x.best_monthly && <Text style={[s.badge, { backgroundColor: colors.success, color: colors.onSuccess }]} testID={`scenario-best-monthly-${i}`}>CHEAPEST MONTHLY</Text>}
                    {x.best_two_year && <Text style={[s.badge, { backgroundColor: colors.brand, color: colors.onBrand }]} testID={`scenario-best-2yr-${i}`}>BEST OVER 2 YRS</Text>}
                  </View>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={[s.val, { fontSize: 16 }]}>{gbp(x.monthly_payment)}</Text>
                  <Text style={[s.muted, { color: x.vs_current > 0 ? colors.error : colors.success }]}>{x.vs_current > 0 ? "+" : ""}{gbp(x.vs_current)} vs {p.mortgage_rate}%</Text>
                </View>
              </View>
            ))}
          </View>
        )}
        <Text style={s.hint}>Estimates only. Lenders will assess affordability and the valuation themselves.</Text>
      </Card>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  rowBetween: { flexDirection: "row", justifyContent: "space-between" },
  row: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  val: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  label: { fontFamily: fonts.medium, fontSize: 12, color: c.muted },
  big: { fontFamily: fonts.extrabold, fontSize: 24 },
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  alert: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1.5, borderColor: c.brandPrimary, padding: space.lg },
  alertIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.orangeTint, alignItems: "center", justifyContent: "center" },
  hint: { fontFamily: fonts.regular, fontSize: 11, color: c.muted, fontStyle: "italic" },
  scen: { flexDirection: "row", alignItems: "center", gap: space.sm, borderWidth: 1.5, borderColor: c.border, borderRadius: radius.md, padding: space.md },
  badge: { fontFamily: fonts.bold, fontSize: 9, letterSpacing: 0.4, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, overflow: "hidden" },
  banner: { borderRadius: radius.md, padding: space.md },
  bannerText: { fontFamily: fonts.semibold, fontSize: 13 },
}));

/** Dashboard heads-up when a personal mortgage's fixed rate ends within 90 days (or has ended). */
export function FixedRateAlertCard({ p }: { p: Project }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const d = p.home_finance.fixed_days_left;
  if (p.purpose !== "personal" || d == null || d > 90) return null;
  return (
    <Pressable testID="fixed-rate-alert-card" onPress={() => router.push("/project-edit")} style={({ pressed }) => [s.alert, pressed && { opacity: 0.9 }]}>
      <View style={s.alertIcon}><Icon name="lock" size={18} color={colors.warning} /></View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.title}>{d < 0 ? "Your fixed rate has ended" : d === 0 ? "Your fixed rate ends today" : `Fixed rate ends in ${d} day${d === 1 ? "" : "s"}`}</Text>
        <Text style={s.muted}>{d < 0 ? "You may now be on the lender's standard variable rate. Compare deals and remortgage." : "Lenders let you lock in a new deal up to 6 months early. Compare your options now."}</Text>
      </View>
      <Icon name="chevron-right" size={18} color={colors.muted} />
    </Pressable>
  );
}
