import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { Image, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BrandLogo } from "@/src/components/brand";
import { Card, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
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

  const { width } = useWindowDimensions();
  const wide = width >= 768;
  const go = (mode: "register" | "login") => router.push({ pathname: "/auth", params: { mode } });

  return (
    <View style={s.root}>
      <View style={[s.topStripe, { height: insets.top + 4 }]} />
      <View style={s.nav}>
        <BrandLogo />
        <Pressable onPress={() => { tap(); go("login"); }} hitSlop={8} style={s.navLink} testID="nav-login-link">
          <Text style={s.navLinkText}>Login</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + space.xl }} showsVerticalScrollIndicator={false}>
        <View style={[s.hero, { minHeight: wide ? 560 : 520 }]} testID="welcome-hero">
          <Image source={require("../assets/images/hero.jpg")} style={s.heroImg} resizeMode="cover" accessibilityIgnoresInvertColors />
          <LinearGradient colors={["rgba(15,23,42,0.35)", colors.scrim]} start={{ x: 0, y: 0 }} end={{ x: wide ? 1 : 0, y: 1 }} style={s.heroImg} />
          <Animated.View entering={FadeInDown.duration(500)} style={[s.heroInner, wide && { alignSelf: "flex-end", maxWidth: 620 }]}>
            <View style={s.pill}>
              <Icon name="sparkles" size={14} color={colors.brandPrimary} />
              <Text style={s.pillText}>FOR UK LANDLORDS, INVESTORS & RENOVATORS</Text>
            </View>
            <Text style={[s.h1, wide && { fontSize: 52, lineHeight: 56 }]} testID="welcome-headline">
              PROPERTY PROJECTS, REIMAGINED. <Text style={{ color: colors.accent }}>PROPERTYPLUG</Text>
            </Text>
            <Text style={s.lead}>
              Effortlessly manage, track and optimise your rentals, tenants and refurbs from one platform. Built for landlords, BRRR investors and DIY renovators.
            </Text>
            <View style={[s.ctas, wide && { flexDirection: "row" }]}>
              <Pressable onPress={() => { tap(); go("register"); }} testID="start-trial-button"
                style={({ pressed }) => [s.ctaPrimary, pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] }]}>
                <Text style={s.ctaPrimaryText}>START FREE TRIAL</Text>
                <View style={s.ctaIcon}><Icon name="play" size={12} color={colors.brand} /></View>
              </Pressable>
              <Pressable onPress={() => { tap(); go("login"); }} testID="sign-in-button"
                style={({ pressed }) => [s.ctaGhost, pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] }]}>
                <Text style={s.ctaGhostText}>SIGN IN</Text>
              </Pressable>
            </View>
            <View style={s.checks}>
              {["1-month free trial", "No card required", "Tenant portal included"].map((t) => (
                <View key={t} style={s.check}>
                  <Icon name="circle-check" size={14} color={colors.accent} />
                  <Text style={s.checkText}>{t}</Text>
                </View>
              ))}
            </View>
          </Animated.View>
        </View>

        <View style={[s.pad, wide && { maxWidth: 900, alignSelf: "center", width: "100%" }]}>
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
  topStripe: { backgroundColor: c.surface, borderBottomWidth: 4, borderBottomColor: c.brand },
  nav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.xl, paddingVertical: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  navLink: { minHeight: 44, justifyContent: "center", paddingHorizontal: space.sm },
  navLinkText: { fontFamily: fonts.semibold, fontSize: 16, color: c.brand },
  hero: { justifyContent: "flex-end", overflow: "hidden", backgroundColor: c.surfaceInverse },
  heroImg: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, width: "100%", height: "100%" },
  heroInner: { paddingHorizontal: space.xl, paddingTop: space.xxxl, paddingBottom: space.xxl, gap: space.lg },
  ctas: { gap: space.md, marginTop: space.sm },
  ctaPrimary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm, minHeight: 52, paddingHorizontal: space.xl, borderRadius: radius.md, backgroundColor: c.brand },
  ctaPrimaryText: { fontFamily: fonts.bold, fontSize: 15, letterSpacing: 0.8, color: c.onBrand },
  ctaIcon: { width: 22, height: 22, borderRadius: 11, backgroundColor: c.onBrand, alignItems: "center", justifyContent: "center", paddingLeft: 2 },
  ctaGhost: { alignItems: "center", justifyContent: "center", minHeight: 52, paddingHorizontal: space.xl, borderRadius: radius.md, borderWidth: 1.5, borderColor: c.onBrand, backgroundColor: "rgba(15,23,42,0.25)" },
  ctaGhostText: { fontFamily: fonts.bold, fontSize: 15, letterSpacing: 0.8, color: c.onBrand },
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
  h1: { fontFamily: fonts.extrabold, fontSize: 36, lineHeight: 40, color: c.onBrand, letterSpacing: -1, textTransform: "uppercase" },
  lead: { fontFamily: fonts.regular, fontSize: 16, lineHeight: 24, color: c.surfaceTertiary },
  checks: { flexDirection: "row", flexWrap: "wrap", gap: space.md },
  check: { flexDirection: "row", alignItems: "center", gap: 4 },
  checkText: { fontFamily: fonts.semibold, fontSize: 12, color: c.surfaceTertiary },
  section: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface, marginTop: space.xxl, marginBottom: space.md },
  feature: { flexDirection: "row", gap: space.md, alignItems: "center" },
  fIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  fTitle: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  fBody: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, marginTop: 2, lineHeight: 18 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: space.xl },
  footerText: { fontFamily: fonts.medium, fontSize: 12, color: c.muted },
}));
