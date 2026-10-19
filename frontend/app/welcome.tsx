import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BrandLogo } from "@/src/components/brand";
import { Button, Card, fonts, Icon, IconName, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const FEATURES: { icon: IconName; title: string; body: string; pro?: boolean }[] = [
  { icon: "key-round", title: "Rent & tenancy tracker", body: "Rent paid or late each month, deposits, renewals, plus auto receipts and annual statements." },
  { icon: "house", title: "Tenant portal", body: "Tenants see their rent history, receipts and certificates, and can report repairs." },
  { icon: "chart-column", title: "Portfolio rent roll", body: "Rent, arrears and net cashflow across every property in your home currency." },
  { icon: "wallet", title: "Refurb budgeting", body: "Hard, soft & contingency costs tracked against actuals, with snags and milestones." },
  { icon: "sparkles", title: "AI cost estimates", body: "UK supplier prices and a finished-room design with cost hotspots." },
  { icon: "calculator", title: "BRRR & remortgage tools", body: "Refinance, money left in, overpayments and remortgage deals compared.", pro: true },
  { icon: "file-check", title: "Lender-ready reports", body: "Progress, budget and rental income proof in one PDF pack.", pro: true },
];

export default function Welcome() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();

  return (
    <View style={s.root}>
      <LinearGradient colors={[colors.brandTertiary, colors.heroEnd]} style={{ position: "absolute", top: 0, left: 0, right: 0, height: 520 }} />
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + space.lg, paddingBottom: insets.bottom + space.xl }} showsVerticalScrollIndicator={false}>
        <View style={s.pad}>
          <BrandLogo />
          <Animated.View entering={FadeInDown.duration(500)} style={{ marginTop: space.xxl, gap: space.lg }}>
            <View style={s.pill}>
              <Icon name="sparkles" size={14} color={colors.brandPrimary} />
              <Text style={s.pillText}>FOR UK LANDLORDS, INVESTORS & RENOVATORS</Text>
            </View>
            <Text style={s.h1} testID="welcome-headline">
              EVERY PROPERTY, ONE APP:
              <Text style={{ color: colors.brand }}> RENT, TENANTS & REFURBS SORTED</Text>
            </Text>
            <Text style={s.lead}>
              Collect rent, keep tenants informed and run refurbs on budget, from purchase to the day it lets. Built for landlords, BRRR investors and DIY renovators.
            </Text>
          </Animated.View>

          <Animated.View entering={FadeInDown.delay(150).duration(500)} style={{ gap: space.md, marginTop: space.xl }}>
            <Button title="START YOUR FREE TRIAL" onPress={() => router.push({ pathname: "/auth", params: { mode: "register" } })} testID="start-trial-button" />
            <Button title="Sign in" variant="outline" onPress={() => router.push({ pathname: "/auth", params: { mode: "login" } })} testID="sign-in-button" />
          </Animated.View>

          <View style={s.checks}>
            {["1-month free trial", "No card required", "Tenant portal included"].map((t) => (
              <View key={t} style={s.check}>
                <Icon name="circle-check" size={14} color={colors.brand} />
                <Text style={s.checkText}>{t}</Text>
              </View>
            ))}
          </View>

          <Text style={s.section}>Everything a landlord needs</Text>
          <View style={{ gap: space.md }}>
            {FEATURES.map((f, i) => (
              <Animated.View key={f.title} entering={FadeInDown.delay(250 + i * 70)}>
                <Card style={s.feature}>
                  <View style={[s.fIcon, f.pro && { backgroundColor: colors.orangeTint }]}>
                    <Icon name={f.icon} size={20} color={f.pro ? colors.brandPrimary : colors.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.fTitle}>
                      {f.title}
                      {f.pro ? <Text style={{ color: colors.brandPrimary, fontSize: 11 }}>  PRO</Text> : null}
                    </Text>
                    <Text style={s.fBody}>{f.body}</Text>
                  </View>
                </Card>
              </Animated.View>
            ))}
          </View>
          <View style={s.footer}>
            <Icon name="shield-check" size={16} color={colors.brandPrimary} />
            <Text style={s.footerText}>Secure UK cloud storage & GDPR compliant</Text>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  pad: { paddingHorizontal: space.xl },
  pill: {
    flexDirection: "row",
    alignSelf: "flex-start",
    alignItems: "center",
    gap: 6,
    backgroundColor: c.orangeTint,
    paddingHorizontal: space.md,
    paddingVertical: 6,
    borderRadius: radius.pill,
  },
  pillText: { fontFamily: fonts.bold, fontSize: 10, color: c.brandPrimary, letterSpacing: 0.6 },
  h1: { fontFamily: fonts.extrabold, fontSize: 32, lineHeight: 38, color: c.onSurface, letterSpacing: -0.8 },
  lead: { fontFamily: fonts.regular, fontSize: 16, lineHeight: 24, color: c.onSurfaceTertiary },
  checks: { flexDirection: "row", flexWrap: "wrap", gap: space.md, marginTop: space.lg },
  check: { flexDirection: "row", alignItems: "center", gap: 4 },
  checkText: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted },
  section: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface, marginTop: space.xxl, marginBottom: space.md },
  feature: { flexDirection: "row", gap: space.md, alignItems: "center" },
  fIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  fTitle: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  fBody: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, marginTop: 2, lineHeight: 18 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: space.xl },
  footerText: { fontFamily: fonts.medium, fontSize: 12, color: c.muted },
}));
