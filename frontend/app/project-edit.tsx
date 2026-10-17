import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, CURRENCIES, CurrencyCode, Project, setCurrency, sym } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { NewProjectTeamPicker } from "@/src/components/new-project-team-picker";
import { CoverChoice, ProjectCoverField, saveCover } from "@/src/components/project-cover-field";
import { invalidate, useProject } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const FINISHES = ["Basic Finish", "Medium Finish", "High Finish"];
const TYPES = [{ v: "residential", l: "Residential" }, { v: "land", l: "Land" }] as const;
const PLANNING = [{ v: "none", l: "No planning" }, { v: "applied", l: "Applied" }, { v: "granted", l: "Granted" }] as const;
const CODES = Object.keys(CURRENCIES) as CurrencyCode[];

export default function ProjectEdit() {
  const { mode } = useLocalSearchParams<{ mode?: string }>();
  const isNew = mode === "new";
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data: p } = useProject();
  const [f, setF] = useState({
    name: "", address: "", purchase_price: "", estimated_valuation: "", monthly_rent: "", refinance_ltv: "75", refinance_rate: "5.5", hard: "", soft: "", contingency: "", finish_type: "Medium Finish",
    currency: "GBP" as CurrencyCode, property_type: "residential" as Project["property_type"], plot_size: "", plot_unit: "acres" as Project["plot_unit"], planning_status: "none" as Project["planning_status"], intended_use: "", value_without_planning: "", value_with_planning: "", lat: "", lon: "",
    purpose: "investment" as Project["purpose"], deposit: "", mortgage_rate: "4.5", mortgage_term: "25", mortgage_type: "repayment" as Project["mortgage_type"], remortgage_ltv: "85", fixed_rate_end: "",
    scen: [{ label: "", rate: "", fee: "" }, { label: "", rate: "", fee: "" }, { label: "", rate: "", fee: "" }],
  });
  const setScen = (i: number, k: "label" | "rate" | "fee") => (v: string) => setF((x) => ({ ...x, scen: x.scen.map((r, j) => (j === i ? { ...r, [k]: v } : r)) }));
  const set = (k: Exclude<keyof typeof f, "scen">) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const [teamIds, setTeamIds] = useState<string[] | null>(null);
  const [cover, setCover] = useState<CoverChoice>({ asset: null, removed: false });
  const isLand = f.property_type === "land";
  const c = sym(f.currency);

  useEffect(() => {
    if (p && !isNew)
      setF({
        name: p.name,
        address: p.address,
        purchase_price: String(p.purchase_price),
        estimated_valuation: String(p.estimated_valuation),
        monthly_rent: String(p.monthly_rent),
        refinance_ltv: String(p.refinance_ltv),
        refinance_rate: String(p.refinance_rate),
        hard: String(p.budget.hard),
        soft: String(p.budget.soft),
        contingency: String(p.budget.contingency),
        finish_type: p.finish_type,
        currency: p.currency,
        property_type: p.property_type,
        plot_size: p.plot_size ? String(p.plot_size) : "",
        plot_unit: p.plot_unit,
        planning_status: p.planning_status,
        intended_use: p.intended_use,
        value_without_planning: p.value_without_planning ? String(p.value_without_planning) : "",
        value_with_planning: p.value_with_planning ? String(p.value_with_planning) : "",
        lat: p.pin_manual && p.lat != null ? String(p.lat) : "",
        lon: p.pin_manual && p.lon != null ? String(p.lon) : "",
        purpose: p.purpose,
        deposit: p.deposit ? String(p.deposit) : "",
        mortgage_rate: String(p.mortgage_rate),
        mortgage_term: String(p.mortgage_term),
        mortgage_type: p.mortgage_type,
        remortgage_ltv: String(p.remortgage_ltv),
        fixed_rate_end: p.fixed_rate_end ?? "",
        scen: [0, 1, 2].map((i) => {
          const r = p.remortgage_scenarios?.[i];
          return r ? { label: r.label, rate: String(r.rate), fee: r.fee ? String(r.fee) : "" } : { label: "", rate: "", fee: "" };
        }),
      });
  }, [p, isNew]);

  const save = useMutation({
    mutationFn: () =>
      api<Project>(isNew ? "/projects" : "/project", {
        method: isNew ? "POST" : "PUT",
        body: {
          name: f.name,
          address: f.address,
          finish_type: f.finish_type,
          purchase_price: Number(f.purchase_price) || 0,
          estimated_valuation: Number(f.estimated_valuation) || 0,
          monthly_rent: isLand ? 0 : Number(f.monthly_rent) || 0,
          refinance_ltv: Number(f.refinance_ltv) || 0,
          refinance_rate: Number(f.refinance_rate) || 0,
          budget: { hard: Number(f.hard) || 0, soft: Number(f.soft) || 0, contingency: Number(f.contingency) || 0 },
          currency: f.currency,
          property_type: f.property_type,
          plot_size: Number(f.plot_size) || 0,
          plot_unit: f.plot_unit,
          planning_status: f.planning_status,
          intended_use: f.intended_use,
          value_without_planning: Number(f.value_without_planning) || 0,
          value_with_planning: Number(f.value_with_planning) || 0,
          purpose: isLand ? "investment" : f.purpose,
          deposit: Number(f.deposit) || 0,
          mortgage_rate: Number(f.mortgage_rate) || 0,
          mortgage_term: Math.min(40, Math.max(1, Math.round(Number(f.mortgage_term) || 25))),
          mortgage_type: f.mortgage_type,
          remortgage_ltv: Math.min(100, Number(f.remortgage_ltv) || 0),
          ...(isNew ? { add_co_owner_ids: teamIds ?? undefined } : { fixed_rate_end: f.fixed_rate_end.trim() || null }),
          remortgage_scenarios: f.scen.filter((r) => Number(r.rate) > 0).map((r) => ({ label: r.label.trim(), rate: Number(r.rate), fee: Number(r.fee) || 0 })),
          ...pin,
        },
      }),
    onSuccess: async (res) => {
      setCurrency(res.currency);
      try {
        await saveCover(cover);
      } catch (e) {
        toast(`Project saved, but the photo didn't upload: ${(e as Error).message}`, "error");
      }
      if (isNew) {
        await queryClient.invalidateQueries();
        toast("Project created and set as active");
        router.dismissTo("/(tabs)");
        return;
      }
      await invalidate("project", "projects");
      toast("Project updated");
      router.back();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const num = { keyboardType: "decimal-pad" as const };
  const hasPin = f.lat.trim() !== "" && f.lon.trim() !== "";
  // Manual pin -> send coords; cleared manual pin -> revert to address geocoding (create endpoint ignores these).
  const pin = hasPin ? { lat: Number(f.lat), lon: Number(f.lon) } : p?.pin_manual && !isNew ? { clear_pin: true } : {};
  const pinError = (f.lat.trim() || f.lon.trim()) && (!hasPin || isNaN(Number(f.lat)) || isNaN(Number(f.lon)) || Math.abs(Number(f.lat)) > 90 || Math.abs(Number(f.lon)) > 180)
    ? "Enter a valid latitude (-90 to 90) and longitude (-180 to 180)" : "";
  const label = { fontFamily: fonts.bold, fontSize: 16, color: colors.onSurface, marginTop: space.sm };
  return (
    <FormScreen
      title={isNew ? "New project" : "Edit project"}
      testID="project-edit-screen"
      footer={<Button title={isNew ? "Create project" : "Save project"} loading={save.isPending} onPress={() => (!f.name.trim() ? toast("Please enter a project name", "error") : pinError ? toast(pinError, "error") : f.fixed_rate_end.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(f.fixed_rate_end.trim()) ? toast("Fixed-rate end date must be YYYY-MM-DD", "error") : f.scen.some((r) => r.rate.trim() && !(Number(r.rate) > 0 && Number(r.rate) <= 30)) ? toast("Remortgage rates must be between 0 and 30%", "error") : save.mutate())} testID="project-save-button" />}
    >
      <Field label="Project name" value={f.name} onChangeText={set("name")} placeholder={isLand ? "e.g. Ashby paddock plot" : "e.g. Derby terrace flip"} testID="project-name-input" />
      <ProjectCoverField current={isNew ? null : p?.cover_path} value={cover} onChange={setCover} />
      <Field label="Address" value={f.address} onChangeText={set("address")} placeholder="Street, town, postcode" testID="project-address-input" />
      <Text style={label}>Property type</Text>
      <View style={{ flexDirection: "row", gap: space.sm }}>
        {TYPES.map((t) => (
          <Chip key={t.v} label={t.l} selected={f.property_type === t.v} onPress={() => set("property_type")(t.v)} testID={`project-type-${t.v}`} />
        ))}
      </View>
      <Text style={label}>Currency</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        {CODES.map((x) => (
          <Chip key={x} label={`${sym(x)} ${x}`} selected={f.currency === x} onPress={() => set("currency")(x)} testID={`project-currency-${x}`} />
        ))}
      </ScrollView>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label={`Purchase (${c})`} value={f.purchase_price} onChangeText={set("purchase_price")} {...num} testID="project-purchase-input" /></View>
        <View style={{ flex: 1 }}><Field label={`Valuation (${c})`} value={f.estimated_valuation} onChangeText={set("estimated_valuation")} {...num} testID="project-valuation-input" /></View>
      </View>
      {isLand ? (
        <>
          <Text style={label}>Land details</Text>
          <View style={{ flexDirection: "row", gap: space.md, alignItems: "flex-end" }}>
            <View style={{ flex: 1 }}><Field label="Plot size" value={f.plot_size} onChangeText={set("plot_size")} {...num} placeholder="0" testID="project-plot-size-input" /></View>
            <View style={{ flexDirection: "row", gap: space.sm, paddingBottom: 6 }}>
              {(["acres", "hectares"] as const).map((u) => (
                <Chip key={u} label={u} selected={f.plot_unit === u} onPress={() => set("plot_unit")(u)} testID={`project-unit-${u}`} />
              ))}
            </View>
          </View>
          <Text style={[label, { fontSize: 13, marginTop: 0 }]}>Planning status</Text>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            {PLANNING.map((x) => (
              <Chip key={x.v} label={x.l} selected={f.planning_status === x.v} onPress={() => set("planning_status")(x.v)} testID={`project-planning-${x.v}`} />
            ))}
          </View>
          <Field label="Intended use" value={f.intended_use} onChangeText={set("intended_use")} placeholder="e.g. 4 self-build plots, grazing, hold for uplift" testID="project-intended-use-input" />
          <View style={{ flexDirection: "row", gap: space.md }}>
            <View style={{ flex: 1 }}><Field label={`Value without planning (${c})`} value={f.value_without_planning} onChangeText={set("value_without_planning")} {...num} testID="project-value-without-input" /></View>
            <View style={{ flex: 1 }}><Field label={`Value with planning (${c})`} value={f.value_with_planning} onChangeText={set("value_with_planning")} {...num} testID="project-value-with-input" /></View>
          </View>
        </>
      ) : (
        <>
          <Text style={label}>Project purpose</Text>
          <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
            <Chip label="Investment (BRRR)" icon="trending-up" selected={f.purpose === "investment"} onPress={() => set("purpose")("investment")} testID="project-purpose-investment" />
            <Chip label="Personal home" icon="house" selected={f.purpose === "personal"} onPress={() => set("purpose")("personal")} testID="project-purpose-personal" />
          </View>
          {f.purpose === "personal" ? (
            <>
              <Text style={{ fontFamily: fonts.regular, fontSize: 12, color: colors.muted }}>BRRR tools are hidden. The dashboard shows your mortgage, equity and remortgage options instead.</Text>
              <View style={{ flexDirection: "row", gap: space.md }}>
                <View style={{ flex: 1 }}><Field label={`Deposit (${c})`} value={f.deposit} onChangeText={set("deposit")} {...num} placeholder="0" testID="project-deposit-input" /></View>
                <View style={{ flex: 1 }}><Field label="Mortgage rate (%)" value={f.mortgage_rate} onChangeText={set("mortgage_rate")} {...num} testID="project-mortgage-rate-input" /></View>
              </View>
              <View style={{ flexDirection: "row", gap: space.md }}>
                <View style={{ flex: 1 }}><Field label="Term (years)" value={f.mortgage_term} onChangeText={set("mortgage_term")} keyboardType="number-pad" testID="project-mortgage-term-input" /></View>
                <View style={{ flex: 1 }}><Field label="Remortgage max LTV (%)" value={f.remortgage_ltv} onChangeText={set("remortgage_ltv")} {...num} testID="project-remortgage-ltv-input" /></View>
              </View>
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Chip label="Repayment" selected={f.mortgage_type === "repayment"} onPress={() => set("mortgage_type")("repayment")} testID="project-mortgage-repayment" />
                <Chip label="Interest-only" selected={f.mortgage_type === "interest_only"} onPress={() => set("mortgage_type")("interest_only")} testID="project-mortgage-interest-only" />
              </View>
              <Field label="Fixed rate ends (optional)" value={f.fixed_rate_end} onChangeText={set("fixed_rate_end")} placeholder="YYYY-MM-DD" testID="project-fixed-end-input" />
              <Text style={label}>Remortgage rates to compare</Text>
              <Text style={{ fontFamily: fonts.regular, fontSize: 12, color: colors.muted }}>Add up to 3 deals. We&apos;ll highlight the cheapest monthly payment and the cheapest over 2 years including fees.</Text>
              {f.scen.map((r, i) => (
                <View key={i} style={{ flexDirection: "row", gap: space.sm }}>
                  <View style={{ flex: 1.3 }}><Field label={`Deal ${i + 1}`} value={r.label} onChangeText={setScen(i, "label")} placeholder="e.g. 2yr fix" testID={`project-scen-label-${i}`} /></View>
                  <View style={{ flex: 1 }}><Field label="Rate %" value={r.rate} onChangeText={setScen(i, "rate")} {...num} testID={`project-scen-rate-${i}`} /></View>
                  <View style={{ flex: 1 }}><Field label={`Fee (${c})`} value={r.fee} onChangeText={setScen(i, "fee")} {...num} testID={`project-scen-fee-${i}`} /></View>
                </View>
              ))}
            </>
          ) : (
            <>
              <Field label={`Expected monthly rent (${c})`} value={f.monthly_rent} onChangeText={set("monthly_rent")} {...num} testID="project-rent-input" />
              <View style={{ flexDirection: "row", gap: space.md }}>
                <View style={{ flex: 1 }}><Field label="Refinance LTV (%)" value={f.refinance_ltv} onChangeText={set("refinance_ltv")} {...num} testID="project-ltv-input" /></View>
                <View style={{ flex: 1 }}><Field label="Mortgage rate (%)" value={f.refinance_rate} onChangeText={set("refinance_rate")} {...num} testID="project-rate-input" /></View>
              </View>
            </>
          )}
        </>
      )}
      <Text style={label}>Budget</Text>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label={`Hard (${c})`} value={f.hard} onChangeText={set("hard")} {...num} testID="project-hard-input" /></View>
        <View style={{ flex: 1 }}><Field label={`Soft (${c})`} value={f.soft} onChangeText={set("soft")} {...num} testID="project-soft-input" /></View>
        <View style={{ flex: 1 }}><Field label="Contingency" value={f.contingency} onChangeText={set("contingency")} {...num} testID="project-contingency-input" /></View>
      </View>
      {!isLand && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {FINISHES.map((x) => (
            <Chip key={x} label={x} selected={f.finish_type === x} onPress={() => set("finish_type")(x)} testID={`project-finish-${x.split(" ")[0].toLowerCase()}`} />
          ))}
        </ScrollView>
      )}
      {isNew && <NewProjectTeamPicker onChange={setTeamIds} />}
      <Text style={label}>Map pin</Text>
      <Text style={{ fontFamily: fonts.regular, fontSize: 12, color: colors.muted, marginTop: -space.sm }}>
        {p?.pin_manual && !isNew ? "Using your coordinates." : "Found automatically from the address. Enter coordinates to place it exactly."}
      </Text>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label="Latitude" value={f.lat} onChangeText={set("lat")} keyboardType="numbers-and-punctuation" placeholder="e.g. 52.9548" testID="project-lat-input" /></View>
        <View style={{ flex: 1 }}><Field label="Longitude" value={f.lon} onChangeText={set("lon")} keyboardType="numbers-and-punctuation" placeholder="e.g. -1.1581" testID="project-lon-input" /></View>
      </View>
      {p?.pin_manual && !isNew && (
        <Button small variant="outline" title="Use address location instead" onPress={() => setF((x) => ({ ...x, lat: "", lon: "" }))} testID="project-clear-pin-button" />
      )}
    </FormScreen>
  );
}
