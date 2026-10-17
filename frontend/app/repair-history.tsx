import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { PdfButton } from "@/src/components/pdf-button";
import { Card, Chip, fonts, FormScreen, Icon, space } from "@/src/components/ui";
import { useCanSeeMoney } from "@/src/money";
import { useProject } from "@/src/queries";
import { shareRepairHistory } from "@/src/report";
import { makeStyles, useTheme } from "@/src/theme";

export type Repair = {
  id: string; room: string; description: string; priority: "low" | "medium" | "high"; status: "open" | "fixed"; source: "tenant" | "snag"; reported_by: string;
  assignee: string; fixed_by: string; created_at: string; fixed_at: string | null; days: number; fix_cost: number | null; fix_note: string; repeat: boolean;
};
export type RepeatFlag = { room: string; count: number; open: number; keywords: string[]; last: string; cost: number; ids: string[] };
export type RepairHistory = { items: Repair[]; repeats: RepeatFlag[]; totals: { count: number; open: number; fixed: number; avg_days_to_fix: number | null; total_cost: number | null; tenant_reported: number } };
type Filter = "all" | "open" | "fixed" | "tenant" | "repeat";
export const dayText = (d: number) => (d < 1 ? "under a day" : `${Math.round(d)} day${Math.round(d) === 1 ? "" : "s"}`);

export default function RepairHistoryScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const money = useCanSeeMoney();
  const { data: project } = useProject();
  const [filter, setFilter] = useState<Filter>("all");
  const q = useQuery({ queryKey: ["repair-history"], queryFn: () => api<RepairHistory>("/repairs/history") });
  const t = q.data?.totals;
  const items = (q.data?.items ?? []).filter((i) => filter === "all" || (filter === "tenant" ? i.source === "tenant" : filter === "repeat" ? i.repeat : i.status === filter));
  const prio = { high: colors.error, medium: colors.brandPrimary, low: colors.muted };

  return (
    <FormScreen title="Repair history" testID="repair-history-screen">
      <View style={s.between}>
        <Text style={[s.muted, { flex: 1 }]}>{project?.name} · every snag and tenant repair, who fixed it, cost and time taken</Text>
        {q.data && <PdfButton onGenerate={() => shareRepairHistory(q.data!, project?.name ?? "Property", money)} testID="repair-history-pdf" />}
      </View>
      {t && (
        <Card style={s.kpis} testID="repair-history-totals">
          <View style={s.kpi}><Text style={s.kv}>{t.count}</Text><Text style={s.muted}>repairs</Text></View>
          <View style={s.kpi}><Text style={[s.kv, { color: t.open ? colors.brandPrimary : colors.onSurface }]}>{t.open}</Text><Text style={s.muted}>open</Text></View>
          <View style={s.kpi}><Text style={s.kv} testID="repair-history-avg">{t.avg_days_to_fix === null ? "–" : t.avg_days_to_fix < 1 ? "<1" : Math.round(t.avg_days_to_fix)}</Text><Text style={s.muted}>avg days to fix</Text></View>
          {money && t.total_cost !== null && <View style={s.kpi}><Text style={s.kv} testID="repair-history-cost">{gbp(t.total_cost)}</Text><Text style={s.muted}>spent</Text></View>}
        </Card>
      )}
      {!!q.data?.repeats.length && (
        <Card style={[{ gap: space.sm, borderColor: colors.brandPrimary, borderWidth: 1.5 }]} testID="repeat-flags">
          <View style={s.between}>
            <Icon name="repeat" size={18} color={colors.brandPrimary} />
            <Text style={[s.name, { flex: 1 }]}>Keeps coming back</Text>
          </View>
          <Text style={s.muted}>Rooms with 2 or more repairs in the last 12 months. Worth finding the root cause.</Text>
          {q.data.repeats.map((r) => (
            <View key={r.room} style={s.flag} testID={`repeat-flag-${r.room.toLowerCase().replace(/\s+/g, "-")}`}>
              <Text style={s.line}>{r.room}: {r.count} repairs{r.open ? ` (${r.open} open)` : ""}{r.keywords.length ? ` · “${r.keywords.join("”, “")}”` : ""}</Text>
              <Text style={s.muted}>Last reported {r.last}{money && r.cost ? ` · ${gbp(r.cost, 2)} spent so far` : ""}</Text>
            </View>
          ))}
        </Card>
      )}
      <View style={s.chips}>
        <Chip label="All" selected={filter === "all"} onPress={() => setFilter("all")} testID="repair-filter-all" />
        <Chip label={`Open${t ? ` (${t.open})` : ""}`} selected={filter === "open"} onPress={() => setFilter("open")} testID="repair-filter-open" />
        <Chip label={`Fixed${t ? ` (${t.fixed})` : ""}`} selected={filter === "fixed"} onPress={() => setFilter("fixed")} testID="repair-filter-fixed" />
        <Chip label={`Tenant reported${t ? ` (${t.tenant_reported})` : ""}`} selected={filter === "tenant"} onPress={() => setFilter("tenant")} testID="repair-filter-tenant" />
        {!!q.data?.repeats.length && <Chip label="Repeats" icon="repeat" selected={filter === "repeat"} onPress={() => setFilter("repeat")} testID="repair-filter-repeat" />}
      </View>
      {q.isLoading ? <ActivityIndicator color={colors.brand} /> : (
        <View style={{ gap: space.sm }}>
          {!items.length && <Text style={[s.muted, { textAlign: "center" }]} testID="repair-history-empty">No repairs here yet.</Text>}
          {items.map((i) => (
            <Card key={i.id} style={{ gap: 4 }} testID={`repair-${i.id}`}>
              <View style={s.between}>
                <Text style={[s.name, { flex: 1 }]} numberOfLines={2}>{i.description}</Text>
                {i.repeat && <Text style={[s.tag, { color: colors.brandPrimary }]} testID={`repair-repeat-${i.id}`}>REPEAT</Text>}
                <Text style={[s.tag, { color: i.status === "fixed" ? colors.success : prio[i.priority] }]}>{i.status === "fixed" ? "FIXED" : i.priority.toUpperCase()}</Text>
              </View>
              <Text style={s.muted}>{i.room} · reported {i.created_at.slice(0, 10)}{i.reported_by ? ` by ${i.reported_by.replace("Tenant: ", "tenant ")}` : ""}</Text>
              {i.status === "fixed" ? (
                <Text style={s.line} testID={`repair-fixed-${i.id}`}>
                  Fixed {i.fixed_at?.slice(0, 10)}{i.fixed_by ? ` by ${i.fixed_by}` : ""} · took {dayText(i.days)}{money && i.fix_cost ? ` · ${gbp(i.fix_cost, 2)}` : ""}
                </Text>
              ) : (
                <Text style={[s.line, { color: colors.brandPrimary }]}>Open {dayText(i.days)}{i.assignee ? ` · assigned to ${i.assignee}` : " · not assigned"}</Text>
              )}
              {i.fix_note ? <Text style={s.muted}>“{i.fix_note}”</Text> : null}
            </Card>
          ))}
        </View>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  kpis: { flexDirection: "row", justifyContent: "space-between", gap: space.sm },
  kpi: { alignItems: "center", flex: 1 },
  kv: { fontFamily: fonts.bold, fontSize: 20, color: c.onSurface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  between: { flexDirection: "row", gap: space.sm, alignItems: "flex-start" },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  tag: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 0.5 },
  flag: { gap: 2, paddingVertical: 4 },
  line: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
