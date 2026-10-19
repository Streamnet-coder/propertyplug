import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BrandLogo } from "@/src/components/brand";
import { Button, Card, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
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

const PREVIEW: { icon: IconName; label: string; value: string; note: string; tone: "brand" | "orange" }[] = [
  { icon: "key-round", label: "Rent collected this month", value: "£4,850", note: "5 of 6 tenancies paid", tone: "brand" },
  { icon: "bell-ring", label: "Arrears chased automatically", value: "£900", note: "Reminder sent today", tone: "orange" },
  { icon: "wallet", label: "Refurb spend vs budget", value: "£18.2k / £22k", note: "On budget · 3 snags open", tone: "brand" },
];

const MAX_W = 1160;

export default function Welcome() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const tablet = width >= 768;
  const desktop = width >= 1024;
  const cols = desktop ? 3 : tablet ? 2 : 1;
  const go = (mode: "register" | "login") => router.push({ pathname: "/auth", params: { mode } });
  const container = [s.pad, { maxWidth: MAX_W, width: "100%" as const, alignSelf: "center" as const }, tablet && { paddingHorizontal: space.xxl }];

  return (
    <View style={s.root}>
      <LinearGradient colors={[colors.brandTertiary, colors.heroEnd, colors.surfaceSecondary]} style={{ position: "absolute", top: 0, left: 0, right: 0, height: desktop ? 680 : 560 }} />
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + space.lg, paddingBottom: insets.bottom + space.xl }} showsVerticalScrollIndicator={false}>
        <View style={container}>
          <View style={s.nav}>
            <BrandLogo />
            {tablet && (
              <Pressable onPress={() => { tap(); go("login"); }} hitSlop={8} style={s.navLink} testID="nav-sign-in-link">
                <Text style={s.navLinkText}>Sign in</Text>
              </Pressable>
            )}
          </View>

          <View style={[s.hero, desktop && s.heroWide]}>
            <View style={desktop ? { flex: 1.1 } : undefined}>
              <Animated.View entering={FadeInDown.duration(500)} style={{ gap: space.lg }}>
                <View style={s.pill}>
                  <Icon name="sparkles" size={14} color={colors.brandPrimary} />
                  <Text style={s.pillText}>FOR UK LANDLORDS, INVESTORS & RENOVATORS</Text>
                </View>
                <Text style={[s.h1, tablet && { fontSize: 44, lineHeight: 50 }, desktop && { fontSize: 54, lineHeight: 60, letterSpacing: -1.4 }]} testID="welcome-headline">
                  EVERY PROPERTY, ONE APP:
                  <Text style={{ color: colors.brand }}> RENT, TENANTS & REFURBS SORTED</Text>
                </Text>
                <Text style={[s.lead, tablet && { fontSize: 18, lineHeight: 28, maxWidth: 560 }]}>
                  Collect rent, keep tenants informed and run refurbs on budget, from purchase to the day it lets. Built for landlords, BRRR investors and DIY renovators.
                </Text>
              </Animated.View>

              <Animated.View entering={FadeInDown.delay(150).duration(500)} style={[s.ctas, tablet && s.ctasRow]}>
                <Button title="START YOUR FREE TRIAL" onPress={() => go("register")} style={tablet && { minWidth: 260 }} testID="start-trial-button" />
                <Button title="Sign in" variant="outline" onPress={() => go("login")} style={tablet && { minWidth: 160 }} testID="sign-in-button" />
              </Animated.View>

              <View style={s.checks}>
                {["1-month free trial", "No card required", "Tenant portal included"].map((t) => (
                  <View key={t} style={s.check}>
                    <Icon name="circle-check" size={14} color={colors.brand} />
                    <Text style={s.checkText}>{t}</Text>
                  </View>
                ))}
              </View>
            </View>

            {tablet && (
              <Animated.View entering={FadeInDown.delay(250).duration(600)} style={[s.preview, desktop ? { flex: 0.9 } : { marginTop: space.xxl }]} testID="welcome-preview">
                <View style={s.previewHead}>
                  <View style={s.dot} /><View style={[s.dot, { backgroundColor: colors.brandPrimary }]} /><View style={[s.dot, { backgroundColor: colors.border }]} />
                  <Text style={s.previewTitle}>Your portfolio at a glance</Text>
                </View>
                {PREVIEW.map((p) => (
                  <View key={p.label} style={s.previewRow}>
                    <View style={[s.fIcon, p.tone === "orange" && { backgroundColor: colors.orangeTint }]}>
                      <Icon name={p.icon} size={20} color={p.tone === "orange" ? colors.brandPrimary : colors.brand} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.previewLabel}>{p.label}</Text>
                      <Text style={s.fBody}>{p.note}</Text>
                    </View>
                    <Text style={[s.previewValue, p.tone === "orange" && { color: colors.brandPrimary }]}>{p.value}</Text>
                  </View>
                ))}
              </Animated.View>
            )}
          </View>

          <Text style={[s.section, tablet && { fontSize: 24, marginTop: space.xxxl, textAlign: desktop ? "center" : "left" }]}>Everything a landlord needs</Text>
          <View style={s.grid} testID="welcome-features">
            {FEATURES.map((f, i) => (
              <Animated.View key={f.title} entering={FadeInDown.delay(250 + i * 70)} style={{ width: cols === 1 ? "100%" : `${100 / cols - 2}%` as const }}>
                <Card style={[s.feature, cols > 1 && s.featureTile]}>
                  <View style={[s.fIcon, f.pro && { backgroundColor: colors.orangeTint }]}>
                    <Icon name={f.icon} size={20} color={f.pro ? colors.brandPrimary : colors.brand} />
                  </View>
                  <View style={cols === 1 ? { flex: 1 } : undefined}>
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

          {tablet && (
            <View style={s.band}>
              <Text style={s.bandTitle}>Ready to run your portfolio from one place?</Text>
              <Button title="START YOUR FREE TRIAL" onPress={() => go("register")} style={{ minWidth: 260 }} testID="start-trial-bottom-button" />
            </View>
          )}
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
  nav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  navLink: { minHeight: 44, justifyContent: "center", paddingHorizontal: space.md },
  navLinkText: { fontFamily: fonts.semibold, fontSize: 16, color: c.brand },
  hero: { marginTop: space.xxl },
  heroWide: { flexDirection: "row", alignItems: "center", gap: space.xxxl, marginTop: space.xxxl },
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
  ctas: { gap: space.md, marginTop: space.xl },
  ctasRow: { flexDirection: "row", alignItems: "center" },
  checks: { flexDirection: "row", flexWrap: "wrap", gap: space.md, marginTop: space.lg },
  check: { flexDirection: "row", alignItems: "center", gap: 4 },
  checkText: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted },
  preview: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md, shadowColor: c.onSurface, shadowOpacity: 0.08, shadowRadius: 24, shadowOffset: { width: 0, height: 12 }, elevation: 4 },
  previewHead: { flexDirection: "row", alignItems: "center", gap: 6, paddingBottom: space.sm, borderBottomWidth: 1, borderBottomColor: c.divider },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.brand },
  previewTitle: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface, marginLeft: space.sm },
  previewRow: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md },
  previewLabel: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  previewValue: { fontFamily: fonts.extrabold, fontSize: 16, color: c.brand },
  section: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface, marginTop: space.xxl, marginBottom: space.md },
  grid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", rowGap: space.md },
  feature: { flexDirection: "row", gap: space.md, alignItems: "center" },
  featureTile: { flexDirection: "column", alignItems: "flex-start", height: "100%", minHeight: 170 },
  fIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  fTitle: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  fBody: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, marginTop: 2, lineHeight: 18 },
  band: { marginTop: space.xxxl, padding: space.xxl, borderRadius: radius.lg, backgroundColor: c.brandTertiary, borderWidth: 1, borderColor: c.border, alignItems: "center", gap: space.lg },
  bandTitle: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onSurface, textAlign: "center" },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: space.xl },
  footerText: { fontFamily: fonts.medium, fontSize: 12, color: c.muted },
}));
