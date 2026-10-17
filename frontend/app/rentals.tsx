import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { gbp, RentMonth, Rentals, Tenancy } from "@/src/api";
import { RenewSheet } from "@/src/components/renew-sheet";
import { SendAllStatements, TenancyActions } from "@/src/components/tenancy-actions";
import { RentLogSheet } from "@/src/components/rent-log-sheet";
import { Button, Card, EmptyState, fonts, Icon, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { invalidate, useRentals } from "@/src/queries";
import { EXPENSE_CATEGORIES, ExpenseCategory, MONTHS, rentTone } from "@/src/rentals";
import { makeStyles, useTheme } from "@/src/theme";

export default function RentalsScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [year, setYear] = useState(new Date().getFullYear());
  const [log, setLog] = useState<{ t: Tenancy; m: RentMonth } | null>(null);
  const [renew, setRenew] = useState<Tenancy | null>(null);
  const q = useRentals(year);
  const d = q.data;

  return (
    <View style={s.root} testID="rentals-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="rentals-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle}>Rent & tenancy</Text>
        <View style={{ width: 44 }} />
      </View>
      <View style={s.yearBar}>
        <Pressable testID="rentals-prev-year" onPress={() => { tap(); setYear(year - 1); }} style={s.iconBtn} hitSlop={6}><Icon name="chevron-left" size={20} /></Pressable>
        <Text style={s.year} testID="rentals-year">{year}</Text>
        <Pressable testID="rentals-next-year" onPress={() => { tap(); setYear(year + 1); }} style={s.iconBtn} hitSlop={6}><Icon name="chevron-right" size={20} /></Pressable>
      </View>

      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError || !d ? (
        <View style={s.center}><Text style={s.muted}>Could not load rental records.</Text><Button small title="Retry" onPress={() => q.refetch()} testID="rentals-retry-button" /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: space.lg, gap: space.xl, paddingBottom: insets.bottom + 120 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => invalidate("rentals")} tintColor={colors.brand} />}
        >
          <Summary d={d} />

          <View>
            <SectionTitle title={`Tenancies (${d.tenancies.length})`} />
            {d.tenancies.some((t) => t.tenant_email) && <SendAllStatements year={year} />}
            {d.tenancies.length === 0 ? (
              <EmptyState icon="key-round" title="No tenancies yet" subtitle="Add your tenant to track rent each month, late payments and the deposit." testID="tenancies-empty" />
            ) : (
              <View style={{ gap: space.md }}>
                {d.tenancies.map((t) => <TenancyCard key={t.id} t={t} year={year} onMonth={(m) => setLog({ t, m })} onRenew={setRenew} />)}
              </View>
            )}
          </View>

          <View>
            <SectionTitle title={`Property expenses (${d.expenses.length})`} />
            {d.expenses.length === 0 ? (
              <Card><Text style={[s.muted, { textAlign: "center" }]} testID="expenses-empty">No expenses logged for {year}. Add repairs, agent fees and insurance to see true net cashflow.</Text></Card>
            ) : (
              <Card style={{ paddingVertical: space.xs }}>
                {d.expenses.map((e, i) => (
                  <Pressable key={e.id} testID={`rental-expense-${e.id}`} onPress={() => { tap(); router.push({ pathname: "/rental-expense-form", params: { id: e.id, year: String(year) } }); }} style={[s.expRow, i > 0 && s.divider]}>
                    <View style={s.expIcon}><Icon name="wrench" size={16} color={colors.brandPrimary} /></View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.expTitle} numberOfLines={1}>{e.description || EXPENSE_CATEGORIES[e.category as ExpenseCategory]}</Text>
                      <Text style={s.muted}>{EXPENSE_CATEGORIES[e.category as ExpenseCategory]} · {e.date}</Text>
                    </View>
                    <Text style={s.expAmt}>-{gbp(e.amount, 2)}</Text>
                  </Pressable>
                ))}
              </Card>
            )}
          </View>
        </ScrollView>
      )}

      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="Tenancy" icon="user-plus" variant="secondary" style={{ flex: 1 }} onPress={() => router.push({ pathname: "/tenancy-form", params: { year: String(year) } })} testID="add-tenancy-button" />
        <Button title="Expense" icon="plus" style={{ flex: 1 }} onPress={() => router.push({ pathname: "/rental-expense-form", params: { year: String(year) } })} testID="add-rental-expense-button" />
      </View>
      <RentLogSheet tenancy={log?.t ?? null} month={log?.m ?? null} onClose={() => setLog(null)} />
      <RenewSheet tenancy={renew} onClose={() => setRenew(null)} />
    </View>
  );
}

function Summary({ d }: { d: Rentals }) {
  const s = useStyles();
  const { colors } = useTheme();
  const sm = d.summary;
  const max = Math.max(1, ...sm.monthly.map((m) => Math.max(m.received, m.expenses)));
  const cats = Object.entries(sm.by_category).sort((a, b) => b[1] - a[1]);
  return (
    <Card style={{ gap: space.lg }} testID="rentals-summary">
      <View>
        <Text style={s.label}>Net cashflow {d.year}</Text>
        <Text style={[s.big, { color: sm.net < 0 ? colors.error : colors.success }]} testID="rentals-net">{gbp(sm.net)}</Text>
      </View>
      <View style={s.cells}>
        <View style={s.cell}><Text style={s.cellVal} testID="rentals-received">{gbp(sm.received)}</Text><Text style={s.muted}>rent received</Text></View>
        <View style={s.cell}><Text style={s.cellVal} testID="rentals-expenses">{gbp(sm.expenses)}</Text><Text style={s.muted}>expenses</Text></View>
        <View style={s.cell}><Text style={[s.cellVal, sm.arrears > 0 && { color: colors.error }]} testID="rentals-arrears">{gbp(sm.arrears)}</Text><Text style={s.muted}>arrears</Text></View>
      </View>
      {max > 1 && (
      <>
      <View style={s.chart} testID="rentals-chart">
        {sm.monthly.map((m, i) => (
          <View key={m.month} style={s.col}>
            <View style={s.bars}>
              <View style={[s.bar, { height: `${(m.received / max) * 100}%`, backgroundColor: colors.brand }]} />
              <View style={[s.bar, { height: `${(m.expenses / max) * 100}%`, backgroundColor: colors.brandPrimary }]} />
            </View>
            <Text style={s.colLabel}>{MONTHS[i][0]}</Text>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", gap: space.lg }}>
        <View style={s.legend}><View style={[s.dot, { backgroundColor: colors.brand }]} /><Text style={s.muted}>Rent</Text></View>
        <View style={s.legend}><View style={[s.dot, { backgroundColor: colors.brandPrimary }]} /><Text style={s.muted}>Expenses</Text></View>
        <Text style={[s.muted, { marginLeft: "auto" }]}>Expected {gbp(sm.rent_due)}</Text>
      </View>
      </>
      )}
      {cats.length > 0 && (
        <View style={{ gap: space.xs }} testID="rentals-categories">
          {cats.map(([k, v]) => (
            <View key={k} style={s.catRow}>
              <Text style={s.catName}>{EXPENSE_CATEGORIES[k as ExpenseCategory] ?? k}</Text>
              <Text style={s.catVal}>{gbp(v)}</Text>
            </View>
          ))}
        </View>
      )}
    </Card>
  );
}

function TenancyCard({ t, year, onMonth, onRenew }: { t: Tenancy; year: number; onMonth: (m: RentMonth) => void; onRenew: (t: Tenancy) => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const statusColor = t.status === "active" ? colors.success : t.status === "upcoming" ? colors.info : colors.muted;
  return (
    <Card style={{ gap: space.md }} testID={`tenancy-card-${t.id}`}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
        <View style={s.avatar}><Text style={s.avatarText}>{t.tenant_name.slice(0, 1).toUpperCase()}</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={s.name} numberOfLines={1}>{t.tenant_name}</Text>
          <Text style={s.muted}>{t.start_date} → {t.end_date ?? "rolling"}</Text>
        </View>
        <View style={[s.pill, { borderColor: statusColor }]}><Text style={[s.pillText, { color: statusColor }]}>{t.status.toUpperCase()}</Text></View>
        <Pressable testID={`tenancy-edit-${t.id}`} onPress={() => { tap(); router.push({ pathname: "/tenancy-form", params: { id: t.id, year: String(year) } }); }} style={s.iconBtn} hitSlop={6}>
          <Icon name="pencil" size={16} />
        </Pressable>
      </View>
      <View style={s.cells}>
        <View style={s.cell}><Text style={s.cellVal} testID={`tenancy-rent-${t.id}`}>{gbp(t.current_rent)}</Text><Text style={s.muted}>rent / mo (day {t.rent_day})</Text></View>
        <View style={s.cell}><Text style={s.cellVal}>{gbp(t.deposit)}</Text><Text style={s.muted} numberOfLines={1}>deposit{t.deposit_scheme ? ` · ${t.deposit_scheme}` : ""}</Text></View>
      </View>
      {t.arrears > 0 && (
        <View style={s.alert} testID={`tenancy-arrears-${t.id}`}>
          <Icon name="circle-alert" size={16} color={colors.error} />
          <Text style={s.alertText}>{gbp(t.arrears, 2)} in arrears · {t.late_count} late month{t.late_count === 1 ? "" : "s"}</Text>
        </View>
      )}
      {(() => {
        const next = t.rent_changes.find((c) => c.from_month >= new Date().toISOString().slice(0, 7));
        return next ? <Text style={s.muted} testID={`tenancy-rent-change-${t.id}`}>{next.from_month > new Date().toISOString().slice(0, 7) ? "Rent changes" : "Rent changed"} to {gbp(next.rent)} from {next.from_month}</Text> : null;
      })()}
      {t.deposit > 0 && !t.deposit_protected && t.status !== "ended" && (
        <View style={[s.alert, { backgroundColor: colors.orangeTint }]} testID={`tenancy-deposit-warning-${t.id}`}>
          <Icon name="shield-alert" size={16} color={colors.warning} />
          <Text style={[s.alertText, { color: colors.warning }]}>Deposit not protected yet. UK law requires this within 30 days</Text>
        </View>
      )}
      {t.days_to_end != null && t.days_to_end <= 60 && (
        <View style={[s.alert, { backgroundColor: colors.orangeTint }]} testID={`tenancy-ending-${t.id}`}>
          <Icon name="calendar-x" size={16} color={colors.warning} />
          <Text style={[s.alertText, { color: colors.warning }]}>{t.days_to_end === 0 ? "Tenancy ends today" : `Tenancy ends in ${t.days_to_end} day${t.days_to_end === 1 ? "" : "s"}`} · plan renewal or re-let</Text>
        </View>
      )}
      {t.schedule.length > 0 ? (
        <View style={s.grid}>
          {t.schedule.map((m) => {
            const tone = rentTone(m.status, colors);
            return (
              <Pressable key={m.month} testID={`rent-month-${t.id}-${m.month}`} onPress={() => { tap(); onMonth(m); }} style={({ pressed }) => [s.month, { backgroundColor: tone.bg }, pressed && { opacity: 0.8 }]}>
                <Text style={[s.monthName, { color: tone.fg }]}>{MONTHS[Number(m.month.slice(5)) - 1]}</Text>
                <Text style={[s.monthVal, { color: tone.fg }]}>{m.status === "paid" ? "✓" : m.paid > 0 ? gbp(m.paid) : m.status === "late" ? "Late" : "–"}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <Text style={s.muted}>No rent due in {year}.</Text>
      )}
      <View style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }}>
        <Text style={[s.hint, { flex: 1, textAlign: "left" }]}>Tap a month to log rent{t.receipts_auto && t.tenant_email ? " · receipts auto-emailed" : ""}</Text>
      </View>
      <TenancyActions t={t} year={year} onRenew={() => onRenew(t)} />
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  yearBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.xl, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  year: { fontFamily: fonts.extrabold, fontSize: 18, color: c.onSurface, minWidth: 60, textAlign: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  big: { fontFamily: fonts.extrabold, fontSize: 32, letterSpacing: -0.8 },
  cells: { flexDirection: "row", gap: space.sm },
  cell: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: space.md, gap: 2 },
  cellVal: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  chart: { flexDirection: "row", height: 96, gap: 4, alignItems: "flex-end" },
  col: { flex: 1, alignItems: "center", gap: 4, height: "100%" },
  bars: { flex: 1, width: "100%", flexDirection: "row", alignItems: "flex-end", justifyContent: "center", gap: 2 },
  bar: { width: "40%", borderTopLeftRadius: 3, borderTopRightRadius: 3, minHeight: 2 },
  colLabel: { fontFamily: fonts.medium, fontSize: 10, color: c.muted },
  legend: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  catRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, borderTopWidth: 1, borderTopColor: c.divider },
  catName: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceTertiary },
  catVal: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.bold, fontSize: 16, color: c.brand },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  pill: { borderWidth: 1.5, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.bold, fontSize: 10, letterSpacing: 0.4 },
  alert: { flexDirection: "row", alignItems: "center", gap: space.sm, backgroundColor: c.errorTint, borderRadius: radius.md, padding: space.md },
  alertText: { fontFamily: fonts.semibold, fontSize: 13, color: c.error, flex: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  month: { width: "15%", flexGrow: 1, minHeight: 48, borderRadius: radius.sm, alignItems: "center", justifyContent: "center", paddingVertical: 6 },
  monthName: { fontFamily: fonts.semibold, fontSize: 11 },
  monthVal: { fontFamily: fonts.bold, fontSize: 12 },
  hint: { fontFamily: fonts.regular, fontSize: 11, color: c.muted, textAlign: "center" },
  expRow: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  expIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.orangeTint, alignItems: "center", justifyContent: "center" },
  expTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  expAmt: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  cta: { position: "absolute", left: space.lg, right: space.lg, flexDirection: "row", gap: space.sm },
}));
