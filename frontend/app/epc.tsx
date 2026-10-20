import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, ProjectEpc } from "@/src/api";
import { Button, Card, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useLayout } from "@/src/layout";
import { invalidate } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

// Official EPC band colours (fixed regardless of app theme).
const BAND: Record<string, string> = { A: "#008054", B: "#19b459", C: "#8dce46", D: "#ffd500", E: "#fcaa65", F: "#ef8023", G: "#e9153b" };

function Badge({ band, rating, testID }: { band?: string | null; rating?: number | null; testID?: string }) {
  const s = useStyles();
  return (
    <View style={[s.badge, { backgroundColor: BAND[band ?? ""] ?? "#94a3b8" }]} testID={testID}>
      <Text style={s.badgeText}>{band ?? "?"}{rating ? ` ${rating}` : ""}</Text>
    </View>
  );
}

export default function EpcPlanner() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const { wide } = useLayout();
  const q = useQuery({ queryKey: ["project-epc"], queryFn: () => api<ProjectEpc>("/project/epc"), retry: false });
  const d = q.data;
  const [picked, setPicked] = useState<number[] | null>(null);
  const [choosing, setChoosing] = useState(false);
  const open = d?.status === "ok" ? d.improvements.filter((x) => !x.in_budget) : [];
  const sel = picked ?? open.map((x) => x.sequence);
  const chosen = open.filter((x) => sel.includes(x.sequence));
  const total = chosen.reduce((a, x) => a + (x.cost_low + x.cost_high) / 2, 0);

  const pin = useMutation({
    mutationFn: (certificate_number: string | null) => api<ProjectEpc>("/project/epc", { method: "PUT", body: { certificate_number } }),
    onSuccess: (r) => { queryClient.setQueryData(["project-epc"], r); setChoosing(false); setPicked(null); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const add = useMutation({
    mutationFn: () => api<{ count: number }>("/project/epc/add-to-budget", { body: { sequences: sel } }),
    onSuccess: async (r) => { setPicked(null); await Promise.all([q.refetch(), invalidate("line-items", "project")]); toast(`${r.count} improvement${r.count === 1 ? "" : "s"} added to your refurb budget`); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const picker = d && d.status !== "no_postcode" && (
    <Card style={{ gap: space.sm }} testID="epc-picker">
      <Text style={s.title}>Which certificate is this property?</Text>
      <Text style={s.muted}>EPCs registered at {d.postcode}. Pick yours to see its rating and upgrade plan.</Text>
      {(d.candidates ?? []).map((c) => (
        <Pressable key={c.certificate_number} onPress={() => { tap(); pin.mutate(c.certificate_number); }} style={s.cand} testID={`epc-cand-${c.certificate_number}`}>
          <Badge band={c.band} />
          <View style={{ flex: 1 }}><Text style={s.name}>{c.address}</Text><Text style={s.muted}>Registered {c.date}</Text></View>
          {pin.isPending && pin.variables === c.certificate_number ? <ActivityIndicator color={colors.brand} /> : <Icon name="chevron-right" size={18} color={colors.muted} />}
        </Pressable>
      ))}
      {!d.candidates?.length && <Text style={s.muted}>No EPCs found at this postcode.</Text>}
    </Card>
  );

  return (
    <View style={s.root} testID="epc-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="epc-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}><Icon name="arrow-left" size={22} /></Pressable>
        <Text style={s.headerTitle}>EPC upgrade planner</Text>
        <View style={{ width: 44 }} />
      </View>
      <ScrollView contentContainerStyle={[{ padding: wide ? space.xl : space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }, wide && { width: "100%", maxWidth: 900, alignSelf: "center" }]}>
        {q.isLoading ? <ActivityIndicator color={colors.brand} style={{ marginTop: space.xl }} /> : q.isError ? (
          <Card style={{ gap: space.sm }} testID="epc-error"><Text style={[s.muted, { color: colors.error }]}>{(q.error as Error).message}</Text><Button small title="Try again" onPress={() => q.refetch()} testID="epc-retry" /></Card>
        ) : d?.status === "no_postcode" ? (
          <Card style={{ gap: space.sm }} testID="epc-no-postcode"><Text style={s.muted}>Add the full address with postcode to this project to look up its EPC.</Text><Button small title="Edit project" onPress={() => router.push("/project-edit")} testID="epc-edit-project" /></Card>
        ) : d?.status === "pick" || choosing ? picker : d?.status === "ok" ? (
          <>
            <Card style={{ gap: space.md }} testID="epc-summary">
              <Text style={s.label}>{d.address} · {d.postcode}</Text>
              <View style={s.bands}>
                <View style={{ alignItems: "center", gap: 4 }}><Badge band={d.band} rating={d.rating} testID="epc-current" /><Text style={s.muted}>Now</Text></View>
                <Icon name="arrow-right" size={22} color={colors.muted} />
                <View style={{ alignItems: "center", gap: 4 }}><Badge band={d.potential_band} rating={d.potential_rating} testID="epc-potential" /><Text style={s.muted}>Potential</Text></View>
              </View>
              <Text style={s.muted}>
                {d.sqft ? `${d.sqft.toLocaleString()} sq ft (${d.sqm} m²) · ` : ""}Registered {d.registration_date}
                {d.heating_cost?.value ? ` · heating about ${gbp(d.heating_cost.value)}/yr` : ""}
              </Text>
              {["E", "F", "G"].includes(d.band ?? "") && <Text style={[s.muted, { color: colors.error }]} testID="epc-letting-warning">Rated below E: it can&apos;t legally be let in England & Wales until improved (or exempt).</Text>}
              <Button small variant="ghost" icon="refresh-cw" title="Not this property? Choose another certificate" onPress={() => setChoosing(true)} testID="epc-change-cert" />
            </Card>
            <Text style={s.section}>Suggested improvements</Text>
            {!d.improvements.length && <Card><Text style={s.muted}>This certificate has no suggested improvements.</Text></Card>}
            {d.improvements.map((x) => {
              const on = !x.in_budget && sel.includes(x.sequence);
              return (
                <Pressable key={x.sequence} disabled={x.in_budget} onPress={() => { tap(); setPicked(on ? sel.filter((y) => y !== x.sequence) : [...sel, x.sequence]); }}
                  style={[s.imp, on && { borderColor: colors.brand }]} testID={`epc-imp-${x.sequence}`}>
                  <View style={[s.box, (on || x.in_budget) && { backgroundColor: x.in_budget ? colors.muted : colors.brand, borderColor: x.in_budget ? colors.muted : colors.brand }]}>
                    {(on || x.in_budget) && <Icon name="check" size={14} color={colors.onBrand} />}
                  </View>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={s.name}>{x.sequence}. {x.name}</Text>
                    <Text style={s.muted}>{x.cost_text || "Cost not given"}{x.saving ? ` · saves about ${gbp(x.saving)}/yr` : ""}</Text>
                    {x.in_budget && <Text style={[s.muted, { color: colors.brand, fontFamily: fonts.semibold }]}>In your refurb budget</Text>}
                  </View>
                  <View style={{ alignItems: "center", gap: 2 }}><Badge band={x.band_after} rating={x.rating_after} /><Text style={s.muted}>after</Text></View>
                </Pressable>
              );
            })}
            {open.length > 0 && (
              <Card style={{ gap: space.sm }} testID="epc-add-card">
                <Text style={s.muted}>{chosen.length} selected · about <Text style={{ fontFamily: fonts.bold, color: colors.onSurface }}>{gbp(total)}</Text> (midpoint of each cost range). Each is added as a Hard Cost line you can edit.</Text>
                <Button icon="plus" title={`Add ${chosen.length} to refurb budget`} disabled={!chosen.length} loading={add.isPending} onPress={() => add.mutate()} testID="epc-add-budget" />
              </Card>
            )}
            <Text style={s.muted}>Source: EPC register (GOV.UK). Costs are the assessor&apos;s indicative ranges; get quotes before committing.</Text>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  section: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  bands: { flexDirection: "row", alignItems: "center", gap: space.lg },
  badge: { minWidth: 52, paddingHorizontal: space.sm, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  badgeText: { fontFamily: fonts.extrabold, fontSize: 16, color: "#0f172a" },
  cand: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 52, borderTopWidth: 1, borderTopColor: c.divider, paddingTop: space.sm },
  imp: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: c.border, alignItems: "center", justifyContent: "center" },
}));
