import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BrrrDeal, BrrrDealInputs, gbp, sym } from "@/src/api";
import { useAuth } from "@/src/auth";
import { PdfButton } from "@/src/components/pdf-button";
import { Button, Card, Field, fonts, Icon, LockedPro, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { BRRR_DEFAULT_COSTS, BRRR_DEFAULT_FEES, calcBrrr, shareBrrrPdf } from "@/src/report";
import { invalidate, useComparables, useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Inputs = Record<keyof BrrrDealInputs, string>;
const KEYS: (keyof BrrrDealInputs)[] = ["purchase", "fees", "refurb", "valuation", "ltv", "rate", "rent", "costs", "months", "bridge_pct", "bridge_rate", "bridge_fee", "holding"];

export default function Brrr() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const { user } = useAuth();
  const isPro = user?.plan === "pro";
  const { data: p } = useProject();
  const comps = useComparables(isPro);
  const toast = useToast();
  const { deal } = useLocalSearchParams<{ deal?: string }>();
  const deals = useQuery({ queryKey: ["brrr-deals"], queryFn: () => api<BrrrDeal[]>("/brrr/deals"), enabled: isPro });
  const loaded = deals.data?.find((d) => d.id === deal);
  const [name, setName] = useState("");
  const [v, setV] = useState<Inputs>({ purchase: "", fees: String(BRRR_DEFAULT_FEES), refurb: "", valuation: "", ltv: "75", rate: "5.5", rent: "", costs: String(BRRR_DEFAULT_COSTS),
    months: "6", bridge_pct: "0", bridge_rate: "0.85", bridge_fee: "2", holding: "0" });
  const set = (k: keyof Inputs) => (t: string) => setV((x) => ({ ...x, [k]: t }));

  useEffect(() => {
    if (loaded) {
      setV(Object.fromEntries(KEYS.map((k) => [k, String(loaded.inputs[k] ?? 0)])) as Inputs);
      setName(loaded.name);
    }
  }, [loaded]);

  useEffect(() => {
    if (p && !deal) setV((x) => ({ ...x, purchase: String(p.purchase_price), refurb: String(p.total_budget), valuation: String(p.estimated_valuation), rent: String(p.monthly_rent), ltv: String(p.refinance_ltv), rate: String(p.refinance_rate) }));
  }, [p]);

  const n = (k: keyof Inputs) => Number(v[k]) || 0;
  const r = useMemo(
    () => calcBrrr(Object.fromEntries(KEYS.map((k) => [k, n(k)])) as BrrrDealInputs),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [v],
  );

  const save = useMutation({
    mutationFn: (asNew: boolean) =>
      api<BrrrDeal>(deal && !asNew ? `/brrr/deals/${deal}` : "/brrr/deals", { method: deal && !asNew ? "PUT" : "POST", body: { name, inputs: Object.fromEntries(KEYS.map((k) => [k, n(k)])) } }),
    onSuccess: async (d) => {
      await invalidate("brrr-deals");
      toast(deal === d.id ? "Deal updated" : "Deal saved");
      router.setParams({ deal: d.id });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const avgComp = comps.data?.length ? comps.data.reduce((a, c) => a + c.price, 0) / comps.data.length : 0;

  const input = (label: string, k: keyof Inputs, suffix?: string) => (
    <View style={s.inWrap}>
      <Text style={s.inLabel}>{label}</Text>
      <View style={s.inBox}>
        {!suffix && <Text style={s.affix}>{sym()}</Text>}
        <TextInput value={v[k]} onChangeText={set(k)} keyboardType="decimal-pad" style={s.in} testID={`brrr-${k}-input`} placeholderTextColor={colors.muted} />
        {suffix && <Text style={s.affix}>{suffix}</Text>}
      </View>
    </View>
  );

  return (
    <View style={s.root} testID="brrr-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="brrr-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>BRRR calculator</Text>
        {isPro ? (
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Pressable testID="brrr-deals-button" onPress={() => { tap(); router.push("/brrr-deals"); }} style={s.back} hitSlop={6} accessibilityLabel="Saved deals">
              <Icon name="folder-open" size={20} />
            </Pressable>
            <PdfButton testID="brrr-pdf-button" onGenerate={() => shareBrrrPdf(r, comps.data ?? [])} />
          </View>
        ) : (
          <View style={{ width: 44 }} />
        )}
      </View>
      {!isPro ? (
        <View style={{ padding: space.lg }}>
          <LockedPro feature="BRRR calculator" description="Model Buy, Refurbish, Refinance, Rent: money left in, cashflow, ROI and 1/4 mile comparables." />
        </View>
      ) : (
        <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xl }}>
          <View style={s.result} testID="brrr-results">
            <Text style={s.resLabel}>Money left in deal</Text>
            <Text style={s.resBig} testID="brrr-money-left-in">{r.leftIn <= 0 ? `${gbp(Math.abs(r.leftIn))} pulled out` : gbp(r.leftIn)}</Text>
            <View style={s.resGrid}>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Cash-on-cash ROI</Text>
                <Text style={s.resVal} testID="brrr-roi">{r.roi === Infinity ? "Infinite" : `${r.roi.toFixed(1)}%`}</Text>
              </View>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Monthly cashflow</Text>
                <Text style={[s.resVal, { color: r.cashflow < 0 ? colors.error : colors.success }]} testID="brrr-cashflow">{gbp(r.cashflow)}</Text>
              </View>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Refinance amount</Text>
                <Text style={s.resVal}>{gbp(r.refi)}</Text>
              </View>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Gross yield</Text>
                <Text style={s.resVal}>{r.yieldPct.toFixed(1)}%</Text>
              </View>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Cash needed upfront</Text>
                <Text style={s.resVal} testID="brrr-cash-needed">{gbp(r.cashNeeded)}</Text>
              </View>
              <View style={s.resCell}>
                <Text style={s.resLabel}>Bridging & holding</Text>
                <Text style={s.resVal} testID="brrr-finance-cost">{gbp(r.financeCost + r.holdingTotal)}</Text>
              </View>
            </View>
          </View>

          <Card style={{ gap: space.md }}>
            <SectionTitle title="Buy & refurbish" />
            <View style={s.row2}>{input("Purchase price", "purchase")}{input("Fees & SDLT", "fees")}</View>
            {input("Refurb budget", "refurb")}
            <Text style={s.hint}>Total invested: <Text style={{ fontFamily: fonts.bold, color: colors.onSurface }}>{gbp(r.invested)}</Text></Text>
          </Card>
          <Card style={{ gap: space.md }} testID="brrr-bridging-card">
            <SectionTitle title="Bridging & time to refinance" />
            <View style={s.row2}>{input("Months to refinance", "months", "mo")}{input("Holding costs", "holding")}</View>
            <View style={s.row2}>{input("Bridging loan", "bridge_pct", "% of price")}{input("Bridge rate", "bridge_rate", "%/mo")}</View>
            {input("Arrangement fee", "bridge_fee", "%")}
            <Text style={s.hint}>
              {r.bridgeLoan > 0 ? <>Bridge {gbp(r.bridgeLoan)} · interest & fee {gbp(r.financeCost)}</> : "No bridging: set a loan % if you're buying with bridging finance"}
              {r.holdingTotal > 0 ? ` · holding ${gbp(r.holdingTotal)}` : ""}. Holding = council tax, insurance, utilities while empty.
            </Text>
          </Card>
          <Card style={{ gap: space.md }}>
            <SectionTitle title="Refinance & rent" />
            {input("End valuation (GDV)", "valuation")}
            <View style={s.row2}>{input("LTV", "ltv", "%")}{input("Interest rate", "rate", "%")}</View>
            <View style={s.row2}>{input("Monthly rent", "rent")}{input("Monthly costs", "costs")}</View>
            <Text style={s.hint}>Mortgage (interest-only): <Text style={{ fontFamily: fonts.bold, color: colors.onSurface }}>{gbp(r.mortgage)}/mo</Text> · Equity retained {gbp(r.equity)}</Text>
          </Card>

          <Card style={{ gap: space.md }} testID="brrr-save-card">
            <SectionTitle title={deal ? "Saved deal" : "Save this deal"} />
            <Field label="Deal name" value={name} onChangeText={setName} placeholder="e.g. 22 Oak St, 3-bed terrace" maxLength={80} testID="brrr-deal-name-input" />
            <View style={s.row2}>
              <Button title={deal ? "Update deal" : "Save deal"} icon="save" style={{ flex: 1 }} loading={save.isPending && !save.variables} disabled={!name.trim()} onPress={() => save.mutate(false)} testID="brrr-save-deal-button" />
              {deal ? <Button title="Save as new" variant="outline" style={{ flex: 1 }} loading={save.isPending && !!save.variables} disabled={!name.trim()} onPress={() => save.mutate(true)} testID="brrr-save-new-button" /> : null}
            </View>
            <Text style={s.hint}>Saved deals can be compared side by side from the folder icon at the top.</Text>
          </Card>

          <View>
            <SectionTitle title="1/4 mile comparables" />
            <Card style={{ paddingVertical: space.xs }} testID="comparables-card">
              {comps.isLoading ? (
                <ActivityIndicator color={colors.brand} style={{ padding: space.lg }} />
              ) : !comps.data?.length ? (
                <Text style={[s.hint, { padding: space.lg, textAlign: "center" }]} testID="comparables-empty">No comparables recorded for this project yet.</Text>
              ) : (
                (comps.data ?? []).map((c, i) => (
                  <View key={c.address} style={[s.comp, i > 0 && s.divider]} testID={`comparable-${i}`}>
                    <View style={s.compIcon}><Icon name="house" size={18} color={colors.brand} /></View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.compAddr}>{c.address}</Text>
                      <Text style={s.hint}>{c.beds} bed · {c.distance} · {c.date}</Text>
                    </View>
                    <Text style={s.compPrice}>{gbp(c.price)}</Text>
                  </View>
                ))
              )}
            </Card>
            {avgComp > 0 && (
              <Text style={[s.hint, { marginTop: space.sm }]} testID="comparables-average">
                Average sold: <Text style={{ fontFamily: fonts.bold, color: colors.brand }}>{gbp(avgComp)}</Text>
                {Number(v.valuation) > avgComp ? " · your GDV is above local comps" : " · your GDV is within local comps"}
              </Text>
            )}
          </View>
        </KeyboardAwareScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    backgroundColor: c.surface,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  result: { backgroundColor: c.brand, borderRadius: radius.lg, padding: space.lg },
  resLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  resBig: { fontFamily: fonts.extrabold, fontSize: 30, color: c.onBrand, marginTop: 2, letterSpacing: -0.5 },
  resGrid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginTop: space.lg },
  resCell: { flexBasis: "47%", flexGrow: 1, backgroundColor: "rgba(255,255,255,0.12)", borderRadius: radius.md, padding: space.md },
  resVal: { fontFamily: fonts.extrabold, fontSize: 18, color: c.onBrand, marginTop: 2 },
  row2: { flexDirection: "row", gap: space.md },
  inWrap: { flex: 1, gap: 6 },
  inLabel: { fontFamily: fonts.semibold, fontSize: 12, color: c.onSurfaceTertiary },
  inBox: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceSecondary,
    paddingHorizontal: space.md,
  },
  affix: { fontFamily: fonts.semibold, fontSize: 15, color: c.muted },
  in: { flex: 1, fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface, paddingHorizontal: 4, minHeight: 46 },
  hint: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  comp: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  compIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  compAddr: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  compPrice: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
}));
