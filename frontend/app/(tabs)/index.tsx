import { Image } from "expo-image";
import { BlurView } from "expo-blur";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useQuery } from "@tanstack/react-query";

import { api, DocItem, expiryLabel, fileUrl, gbp } from "@/src/api";
import { useAuth } from "@/src/auth";
import { BrandLogo } from "@/src/components/brand";
import { Button, Card, fonts, Icon, ProBadge, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { MAX_CONTENT, useLayout } from "@/src/layout";
import { useQuickActions } from "@/src/quick-actions";
import { usesNativeTabs } from "@/src/navigation";
import { PdfButton } from "@/src/components/pdf-button";
import { invalidate, prefetchProjects, useDigest, useLineItems, useProject, useReceipts } from "@/src/queries";
import { shareProgressReport } from "@/src/report";
import { LandUplift, PlanningCard } from "@/src/components/land-cards";
import { ExpiringAccessCard } from "@/src/components/expiring-access-card";
import { OverdueRequestsCard } from "@/src/components/overdue-requests-card";
import { RentalsCard, TenancyAlertsCard } from "@/src/components/rentals-card";
import { useCanSeeMoney } from "@/src/money";
import { OwnershipSplitCard } from "@/src/components/ownership-split-card";
import { PhotoTimelineCard } from "@/src/components/photo-timeline-card";
import { FixedRateAlertCard, HomeFinanceCard } from "@/src/components/home-finance-card";
import { makeStyles, useTheme } from "@/src/theme";

const HERO = "https://images.unsplash.com/photo-1714259830228-893a69a2d45b?crop=entropy&cs=srgb&fm=jpg&ixlib=rb-4.1.0&q=85&w=1200";

export default function Home() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const { user } = useAuth();
  const project = useProject();
  const money = useCanSeeMoney();
  const { wide } = useLayout();
  const receipts = useReceipts(money);
  const digest = useDigest(0);
  const lineItems = useLineItems(money);
  const expiring = useQuery({ queryKey: ["documents", "expiring"], queryFn: () => api<DocItem[]>("/documents/expiring") });
  const over = (lineItems.data ?? []).filter((i) => i.alert === "over").length;
  const near = (lineItems.data ?? []).filter((i) => i.alert === "near").length;
  useEffect(() => { prefetchProjects(); }, []);
  const p = project.data;
  const isPro = user?.plan === "pro";

  const pct = p && p.total_budget > 0 ? Math.min(100, Math.round((p.total_spent / p.total_budget) * 100)) : 0;
  const trialDays = user ? Math.max(0, Math.ceil((new Date(user.trial_ends).getTime() - Date.now()) / 86400000)) : 0;

  const rows = p
    ? [
        { label: "Hard costs", b: p.budget.hard, sp: p.spent.hard, color: colors.brand },
        { label: "Soft costs", b: p.budget.soft, sp: p.spent.soft, color: colors.accent },
        { label: "Contingency", b: p.budget.contingency, sp: p.spent.contingency, color: colors.brandPrimary },
      ]
    : [];

  const msPct = p && p.milestones_total ? Math.round((p.milestones_done / p.milestones_total) * 100) : 0;

  const { actions } = useQuickActions();

  return (
    <View style={s.root} testID="home-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        {!wide && <BrandLogo />}
        <View style={{ flex: 1 }} />
        <PdfButton onGenerate={shareProgressReport} testID="dashboard-pdf-button" />
        <Pressable testID="profile-button" onPress={() => { tap(); router.push("/profile"); }} style={s.avatar}>
          <Text style={s.avatarText}>{user?.name?.charAt(0).toUpperCase()}</Text>
        </Pressable>
      </View>

      {project.isLoading ? (
        <View style={s.center}>
          <ActivityIndicator color={colors.brand} />
        </View>
      ) : project.isError || !p ? (
        <View style={s.center}>
          <Text style={s.muted}>{(project.error as Error | null)?.message === "Project not found" ? "No projects yet. Create your own, or open one shared with you." : "Couldn't load your project."}</Text>
          <Button small title="Retry" onPress={() => project.refetch()} testID="home-retry-button" />
          <Button small variant="outline" icon="plus" title="Create a project" onPress={() => router.push({ pathname: "/project-edit", params: { mode: "new" } })} testID="home-create-project-button" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={[{ padding: wide ? space.xl : space.lg, paddingBottom: bottomChrome + 100, gap: space.xl }, s.contained]}
          refreshControl={<RefreshControl refreshing={project.isRefetching} onRefresh={() => invalidate("project", "receipts", "digest", "line-items")} tintColor={colors.brand} />}
          showsVerticalScrollIndicator={false}
        >
          <View style={wide ? s.cols : s.stack}>
          <View style={wide ? s.colMain : s.stack}>
          <Animated.View entering={FadeInDown.duration(400)} style={[s.hero, wide && { height: 320 }]} testID="project-hero-card">
            <Image source={{ uri: p.cover_path ? fileUrl(p.cover_path) : HERO }} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} contentFit="cover" transition={300} testID={p.cover_path ? "hero-cover-photo" : "hero-stock-photo"} />
            <LinearGradient colors={["rgba(15,23,42,0.35)", "rgba(15,23,42,0.05)", colors.scrim]} locations={[0, 0.35, 1]} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
            <View style={s.heroTop}>
              <View style={s.heroTag}>
                <Text style={s.heroTagText}>{p.target_type.toUpperCase()}</Text>
              </View>
              <View style={{ flexDirection: "row", gap: space.sm }}>
                {!p.cover_path && !user?.acting_as && (
                  <Pressable testID="hero-add-photo" onPress={() => { tap(); router.push("/project-edit"); }} style={s.switchBtn} hitSlop={6}>
                    <Icon name="camera" size={14} color={colors.onSurfaceInverse} />
                    <Text style={s.switchText}>Add photo</Text>
                  </Pressable>
                )}
                <Pressable testID="switch-project-button" onPress={() => { tap(); router.push("/projects"); }} style={s.switchBtn} hitSlop={6}>
                  <Icon name="arrow-left-right" size={14} color={colors.onSurfaceInverse} />
                  <Text style={s.switchText}>Switch</Text>
                </Pressable>
              </View>
            </View>
            <View style={{ marginTop: "auto", gap: space.xs }}>
              {user?.acting_as && (
                <View style={s.coPill} testID="co-owner-banner">
                  <Icon name="users" size={12} color={colors.onSurfaceInverse} />
                  <Text style={s.switchText}>Co-owner · {user.acting_as.owner_name}&apos;s project</Text>
                </View>
              )}
              <Text style={s.heroTitle} testID="project-name">{p.name}</Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Icon name="map-pin" size={13} color={colors.onSurfaceInverse} />
                <Text style={s.heroAddr} numberOfLines={1}>{p.address}</Text>
              </View>
              {money ? (<>
              <View style={s.heroMetrics}>
                <View>
                  <Text style={s.heroLabel}>Spent vs budget</Text>
                  <Text style={s.heroBig} testID="project-total-spent">
                    {gbp(p.total_spent)} <Text style={s.heroOf}>/ {gbp(p.total_budget)}</Text>
                  </Text>
                </View>
                <View style={[s.pctPill, pct > 90 && { backgroundColor: colors.warning }]}>
                  <Text style={s.pctText} testID="project-spend-percent">{pct}% used</Text>
                </View>
              </View>
              <View style={s.bar}>
                <View style={[s.barFill, { width: `${pct}%` }]} />
              </View>
              </>) : (
                <View style={s.heroMetrics}>
                  <View>
                    <Text style={s.heroLabel}>Tasks access · money figures hidden</Text>
                    <Text style={s.heroBig} testID="project-stage-progress">{msPct}% <Text style={s.heroOf}>of stages done</Text></Text>
                  </View>
                </View>
              )}
            </View>
          </Animated.View>

          {!isPro && (
            <Pressable testID="trial-banner" onPress={() => router.push("/profile")} style={s.trial}>
              <Icon name="crown" size={18} color={colors.brandPrimary} />
              <Text style={s.trialText}>
                Basic plan · {trialDays} trial days left. <Text style={{ fontFamily: fonts.bold, color: colors.brandPrimary }}>Unlock Pro</Text>
              </Text>
              <Icon name="chevron-right" size={18} color={colors.brandPrimary} />
            </Pressable>
          )}

          {!wide && <View style={s.actions}>
            {actions.map((a, i) => (
              <Animated.View key={a.id} entering={FadeInDown.delay(80 + i * 60)} style={{ flex: 1 }}>
                <Pressable testID={`quick-action-${a.id}`} onPress={() => { tap(); a.onPress(); }} style={({ pressed }) => [s.action, pressed && { transform: [{ scale: 0.96 }] }]}>
                  <View style={[s.actionIcon, a.pro && { backgroundColor: colors.orangeTint }]}>
                    <Icon name={a.icon} size={20} color={a.pro ? colors.brandPrimary : colors.brand} />
                  </View>
                  <Text style={s.actionLabel} numberOfLines={1}>{a.label}</Text>
                  {a.pro && !isPro && <View style={{ position: "absolute", top: 6, right: 6 }}><ProBadge locked /></View>}
                </Pressable>
              </Animated.View>
            ))}
          </View>}

          <Pressable testID="timeline-card" onPress={() => { tap(); router.push("/timeline"); }} style={({ pressed }) => [s.timeline, pressed && { opacity: 0.9 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
              <View style={s.tlIcon}><Icon name="milestone" size={20} color={colors.brand} /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.rowLabel}>Milestones</Text>
                <Text style={s.muted} numberOfLines={1} testID="timeline-current-stage">
                  {p.current_stage ? `Now: ${p.current_stage}` : "Add your first stage"}
                </Text>
              </View>
              <Text style={s.rowVal} testID="timeline-card-progress">{p.milestones_done}/{p.milestones_total}</Text>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </View>
            <View style={s.segRow}>
              {Array.from({ length: p.milestones_total }).map((_, i) => (
                <View key={i} style={[s.seg, { backgroundColor: i < p.milestones_done ? colors.success : i === p.milestones_done ? colors.brandPrimary : colors.surfaceTertiary }]} />
              ))}
            </View>
            <Text style={s.muted}>{msPct}% of stages complete</Text>
          </Pressable>

          {money && over + near > 0 && (
            <Pressable testID="variance-alert-card" onPress={() => { tap(); router.push("/budget"); }} style={[s.alertCard, { borderColor: over ? colors.error : colors.brandPrimary }]}>
              <Icon name="triangle-alert" size={20} color={over ? colors.error : colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={s.rowLabel}>Budget variance alert</Text>
                <Text style={s.muted}>{[over && `${over} item${over === 1 ? "" : "s"} over budget`, near && `${near} at 90%+`].filter(Boolean).join(" · ")}</Text>
              </View>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </Pressable>
          )}

          <PhotoTimelineCard p={p} />
          <ExpiringAccessCard linkToPortal />
          <OverdueRequestsCard />
          {money && p.property_type !== "land" && <TenancyAlertsCard />}
          {money && <FixedRateAlertCard p={p} />}

          {(expiring.data ?? []).length > 0 && (
            <Pressable testID="expiry-alert-card" onPress={() => { tap(); router.push("/documents"); }} style={[s.alertCard, { borderColor: expiring.data!.some((d) => d.expiry_status === "expired") ? colors.error : colors.brandPrimary }]}>
              <Icon name="calendar-clock" size={20} color={expiring.data!.some((d) => d.expiry_status === "expired") ? colors.error : colors.brandPrimary} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.rowLabel}>Certificates & insurance</Text>
                {expiring.data!.slice(0, 3).map((d) => (
                  <Text key={d.id} style={[s.muted, d.expiry_status === "expired" && { color: colors.error, fontFamily: fonts.semibold }]} numberOfLines={1} testID={`expiry-item-${d.id}`}>
                    {d.doc_type}: {expiryLabel(d)}
                  </Text>
                ))}
                {expiring.data!.length > 3 && <Text style={s.muted}>+{expiring.data!.length - 3} more</Text>}
              </View>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </Pressable>
          )}

          <Pressable testID="documents-card" onPress={() => { tap(); router.push("/documents"); }} style={({ pressed }) => [s.timeline, pressed && { opacity: 0.9 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
              <View style={s.tlIcon}><Icon name="folder-open" size={20} color={colors.brand} /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.rowLabel}>Documents</Text>
                <Text style={s.muted}>Deeds, surveys, certificates & invoices · share with stakeholders</Text>
              </View>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </View>
          </Pressable>

          <Pressable testID="digest-card" onPress={() => { tap(); router.push("/digest"); }} style={({ pressed }) => [s.timeline, pressed && { opacity: 0.9 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
              <View style={s.tlIcon}><Icon name="calendar-days" size={20} color={colors.brand} /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.rowLabel}>This week</Text>
                <Text style={s.muted}>Spend, snags fixed & stages hit</Text>
              </View>
              <Icon name="chevron-right" size={18} color={colors.muted} />
            </View>
            <View style={s.digestRow}>
              <View style={s.digestCell}>
                <Text style={s.statVal} testID="digest-card-spend">{gbp(digest.data?.spend.total ?? 0)}</Text>
                <Text style={s.muted}>spent</Text>
              </View>
              <View style={s.digestCell}>
                <Text style={s.statVal} testID="digest-card-snags">{digest.data?.snags_fixed.length ?? 0}</Text>
                <Text style={s.muted}>snags fixed</Text>
              </View>
              <View style={s.digestCell}>
                <Text style={s.statVal} testID="digest-card-milestones">{digest.data?.milestones_done.length ?? 0}</Text>
                <Text style={s.muted}>stages done</Text>
              </View>
            </View>
          </Pressable>
          </View>

          <View style={wide ? s.colSide : s.stack} testID={wide ? "home-side-column" : undefined}>
          {money && (<>
          <View>
            <SectionTitle title="Budget breakdown" action="Details" onAction={() => router.push("/(tabs)/budget")} testID="budget-details-link" />
            <Card style={{ gap: space.lg }}>
              {rows.map((r) => {
                const rp = r.b > 0 ? Math.min(100, (r.sp / r.b) * 100) : 0;
                const over = r.sp > r.b;
                return (
                  <View key={r.label} style={{ gap: 6 }} testID={`breakdown-${r.label.split(" ")[0].toLowerCase()}`}>
                    <View style={s.rowBetween}>
                      <Text style={s.rowLabel}>{r.label}</Text>
                      <Text style={[s.rowVal, over && { color: colors.error }]}>
                        {gbp(r.sp)} <Text style={s.muted}>/ {gbp(r.b)}</Text>
                      </Text>
                    </View>
                    <View style={s.track}>
                      <View style={[s.trackFill, { width: `${rp}%`, backgroundColor: over ? colors.error : r.color }]} />
                    </View>
                  </View>
                );
              })}
            </Card>
          </View>

          <View>
            <SectionTitle title="Deal snapshot" />
            <View style={s.grid}>
              <Card style={s.stat}>
                <Text style={s.statLabel}>Purchase</Text>
                <Text style={s.statVal}>{gbp(p.purchase_price)}</Text>
              </Card>
              <Card style={s.stat}>
                <Text style={s.statLabel}>Est. valuation</Text>
                <Text style={s.statVal}>{gbp(p.estimated_valuation)}</Text>
              </Card>
              <Card style={s.stat}>
                <Text style={s.statLabel}>Uplift</Text>
                <Text style={[s.statVal, { color: colors.success }]}>{gbp(p.estimated_valuation - p.purchase_price - p.total_budget)}</Text>
              </Card>
              <Card style={s.stat}>
                <Text style={s.statLabel}>{p.property_type === "land" ? "Planning" : "Finish"}</Text>
                <Text style={s.statVal} numberOfLines={1}>{p.property_type === "land" ? { none: "None", applied: "Applied", granted: "Granted" }[p.planning_status] : p.finish_type}</Text>
              </Card>
            </View>
          </View>

          {p.property_type === "land" ? (
          <View>
            <SectionTitle title="Land details" action="Edit" onAction={() => router.push("/project-edit")} testID="land-details-edit" />
            <Card style={{ gap: space.md }} testID="land-details-card">
              <View style={s.digestRow}>
                <View style={s.digestCell}><Text style={s.rowVal} testID="land-plot-size">{p.plot_size ? `${p.plot_size} ${p.plot_unit}` : "-"}</Text><Text style={s.muted}>plot size</Text></View>
                <View style={s.digestCell}><Text style={s.rowVal} testID="land-planning-status">{{ none: "None", applied: "Applied", granted: "Granted" }[p.planning_status]}</Text><Text style={s.muted}>planning</Text></View>
              </View>
              <Text style={s.muted} testID="land-intended-use">Intended use: {p.intended_use || "Not set"}</Text>
              {p.plot_size > 0 && p.purchase_price > 0 && <Text style={s.muted}>{gbp(p.purchase_price / p.plot_size)} per {p.plot_unit === "acres" ? "acre" : "hectare"} paid</Text>}
            </Card>
            <LandUplift p={p} />
            <PlanningCard />
          </View>
          ) : (
          <View>
            {p.purpose === "personal" ? <HomeFinanceCard p={p} /> : (<>
            <SectionTitle title="Rent & refinance" action="Edit" onAction={() => router.push("/project-edit")} testID="rent-yield-edit" />
            {p.monthly_rent > 0 ? (
              <Card style={{ gap: space.md }} testID="rent-yield-card">
                <View style={s.rowBetween}>
                  <View>
                    <Text style={s.statLabel}>Gross yield</Text>
                    <Text style={[s.statVal, { color: colors.brand, fontSize: 24 }]} testID="rent-gross-yield">{p.rent_yield.gross_yield.toFixed(1)}%</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={s.statLabel}>{p.rent_yield.cash_left_in > 0 ? "Cash left in deal" : "Cash pulled out"}</Text>
                    <Text style={[s.statVal, { fontSize: 24, color: p.rent_yield.cash_left_in > 0 ? colors.onSurface : colors.success }]} testID="rent-cash-left-in">{gbp(Math.abs(p.rent_yield.cash_left_in))}</Text>
                  </View>
                </View>
                <View style={s.digestRow}>
                  <View style={s.digestCell}><Text style={s.rowVal}>{gbp(p.monthly_rent)}</Text><Text style={s.muted}>rent / mo</Text></View>
                  <View style={s.digestCell}><Text style={s.rowVal} testID="rent-refi-amount">{gbp(p.rent_yield.refinance_amount)}</Text><Text style={s.muted}>refi at {p.refinance_ltv}% LTV</Text></View>
                  <View style={s.digestCell}><Text style={[s.rowVal, { color: p.rent_yield.monthly_cashflow < 0 ? colors.error : colors.success }]}>{gbp(p.rent_yield.monthly_cashflow)}</Text><Text style={s.muted}>cashflow / mo</Text></View>
                </View>
                <Text style={s.muted}>Yield on cost {p.rent_yield.yield_on_cost.toFixed(1)}% · {gbp(p.rent_yield.invested)} in (purchase + budget) · {p.refinance_rate}% interest-only</Text>
              </Card>
            ) : (
              <Pressable testID="rent-yield-empty" onPress={() => router.push("/project-edit")} style={s.trial}>
                <Icon name="house" size={18} color={colors.brandPrimary} />
                <Text style={s.trialText}>Add your expected rent to see yield and cash left in after refinance</Text>
                <Icon name="chevron-right" size={18} color={colors.brandPrimary} />
              </Pressable>
            )}
            </>)}
            <RentalsCard />
            {money && <OwnershipSplitCard />}
          </View>
          )}

          <View>
            <SectionTitle title="Recent receipts" action="See all" onAction={() => router.push({ pathname: "/(tabs)/media", params: { tab: "receipts" } })} testID="receipts-see-all" />
            <Card style={{ paddingVertical: space.xs }}>
              {(receipts.data ?? []).slice(0, 3).map((r, i) => (
                <View key={r.id} style={[s.receipt, i > 0 && s.divider]} testID={`recent-receipt-${r.id}`}>
                  <View style={s.rIcon}>
                    <Icon name="receipt" size={18} color={colors.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.rTitle} numberOfLines={1}>{r.title}</Text>
                    <Text style={s.muted}>{r.supplier} · {r.date}</Text>
                  </View>
                  <Text style={s.rAmt}>{gbp(r.amount, 2)}</Text>
                </View>
              ))}
              {receipts.data?.length === 0 && <Text style={[s.muted, { padding: space.lg, textAlign: "center" }]}>No receipts yet</Text>}
            </Card>
          </View>
          </>)}
          {!money && p.property_type === "land" && <PlanningCard />}
          </View>
          </View>
        </ScrollView>
      )}

      {p && money && (
        <BlurView intensity={40} tint="light" style={wide ? s.ctaWide : [s.cta, { paddingBottom: bottomChrome + space.md }]}>
          <Button title="Add Expense" icon="plus" onPress={() => router.push("/receipt-form")} testID="add-expense-button" />
        </BlurView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  contained: { width: "100%", maxWidth: MAX_CONTENT, alignSelf: "center" },
  stack: { gap: space.xl },
  cols: { flexDirection: "row", alignItems: "flex-start", gap: space.xl },
  colMain: { flex: 1.25, minWidth: 0, gap: space.xl },
  colSide: { flex: 1, minWidth: 0, gap: space.xl },
  ctaWide: { position: "absolute", right: space.xl, bottom: space.xl, width: 280, padding: space.md, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, backgroundColor: "rgba(255,255,255,0.85)", overflow: "hidden" },
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
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 16, color: c.onBrand },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  hero: { height: 260, borderRadius: radius.lg, overflow: "hidden", padding: space.lg, backgroundColor: c.surfaceInverse },
  heroTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  coPill: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill, backgroundColor: "rgba(255,255,255,0.18)" },
  switchBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 36,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    backgroundColor: "rgba(15,23,42,0.55)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.3)",
  },
  switchText: { fontFamily: fonts.bold, fontSize: 12, color: c.onSurfaceInverse },
  heroTag: { alignSelf: "flex-start", backgroundColor: c.brandPrimary, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  heroTagText: { fontFamily: fonts.bold, fontSize: 10, color: c.onBrandPrimary, letterSpacing: 0.6 },
  heroTitle: { fontFamily: fonts.extrabold, fontSize: 22, color: c.onSurfaceInverse, letterSpacing: -0.4 },
  heroAddr: { fontFamily: fonts.medium, fontSize: 12, color: c.onSurfaceInverse, opacity: 0.85, flex: 1 },
  heroMetrics: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", marginTop: space.md },
  heroLabel: { fontFamily: fonts.medium, fontSize: 11, color: c.onSurfaceInverse, opacity: 0.8 },
  heroBig: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onSurfaceInverse },
  heroOf: { fontFamily: fonts.medium, fontSize: 13, opacity: 0.8 },
  pctPill: { backgroundColor: c.brand, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.md },
  pctText: { fontFamily: fonts.bold, fontSize: 12, color: c.onBrand },
  bar: { height: 6, borderRadius: 3, backgroundColor: "rgba(255,255,255,0.25)", marginTop: space.sm, overflow: "hidden" },
  barFill: { height: 6, borderRadius: 3, backgroundColor: c.brandPrimary },
  trial: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    backgroundColor: c.orangeTint,
    padding: space.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.orangeBorder,
  },
  trialText: { flex: 1, fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceSecondary },
  actions: { flexDirection: "row", gap: space.sm },
  action: {
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    paddingVertical: space.md,
    alignItems: "center",
    gap: 6,
  },
  actionIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  actionLabel: { fontFamily: fonts.semibold, fontSize: 11, color: c.onSurfaceSecondary },
  timeline: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  tlIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  alertCard: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.lg, borderRadius: radius.lg, borderWidth: 1.5, backgroundColor: c.surface },
  digestRow: { flexDirection: "row", gap: space.sm },
  digestCell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.sm, gap: 2 },
  segRow: { flexDirection: "row", gap: 4 },
  seg: { flex: 1, height: 8, borderRadius: 4 },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  rowLabel: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurfaceSecondary },
  rowVal: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  track: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  trackFill: { height: 8, borderRadius: 4 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.md },
  stat: { flexBasis: "47%", flexGrow: 1, padding: space.md, gap: 4 },
  statLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.muted },
  statVal: { fontFamily: fonts.extrabold, fontSize: 18, color: c.onSurface },
  receipt: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  rIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  rTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  rAmt: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  cta: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: space.lg, paddingTop: space.md, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: "rgba(255,255,255,0.72)", overflow: "hidden" },
}));
