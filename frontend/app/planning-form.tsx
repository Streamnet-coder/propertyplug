import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, PlanningApp } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate, usePlanning } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { DECISIONS } from "@/src/planning";

const DATES = [
  { k: "submitted_date", l: "Submitted" },
  { k: "validated_date", l: "Validated" },
  { k: "consultation_end", l: "Consultation ends" },
  { k: "target_decision_date", l: "Target decision date" },
] as const;

const EMPTY = { authority: "", reference: "", description: "", submitted_date: "", validated_date: "", consultation_end: "", target_decision_date: "", decision: "pending" as PlanningApp["decision"], decision_date: "", notes: "" };

export default function PlanningForm() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data } = usePlanning();
  const existing = data?.find((a) => a.id === id);
  const [f, setF] = useState(EMPTY);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (existing) setF(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, (existing as any)[k] ?? ""])) as typeof EMPTY);
  }, [existing]);

  const done = async (msg: string) => {
    await invalidate("planning");
    toast(msg);
    router.back();
  };
  const body = () => Object.fromEntries(Object.entries(f).map(([k, v]) => [k, typeof v === "string" ? v.trim() || (k.endsWith("_date") || k === "consultation_end" ? null : "") : v]));
  const save = useMutation({
    mutationFn: () => api(id ? `/planning/${id}` : "/planning", { method: id ? "PUT" : "POST", body: body() }),
    onSuccess: () => done(id ? "Application updated" : "Application added"),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({ mutationFn: () => api(`/planning/${id}`, { method: "DELETE" }), onSuccess: () => done("Application removed") });

  const submit = () => {
    setError("");
    if (!f.reference.trim() && !f.description.trim()) return setError("Enter a reference number or description");
    const bad = [...DATES.map((d) => f[d.k]), f.decision_date].find((v) => v.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(v.trim()));
    if (bad) return setError("Use date format YYYY-MM-DD");
    save.mutate();
  };

  return (
    <FormScreen
      title={id ? "Edit application" : "New planning application"}
      testID="planning-form-screen"
      footer={
        <>
          <Button title={id ? "Save application" : "Add application"} loading={save.isPending} onPress={submit} testID="planning-save-button" />
          {id && <Button variant="danger" icon="trash-2" title="Delete application" loading={remove.isPending} onPress={() => remove.mutate()} testID="planning-delete-button" />}
        </>
      }
    >
      <Field label="Reference number" value={f.reference} onChangeText={set("reference")} placeholder="e.g. 24/01234/FUL" autoCapitalize="characters" testID="planning-reference-input" />
      <Field label="Council / planning authority" value={f.authority} onChangeText={set("authority")} placeholder="e.g. Rushcliffe Borough Council" testID="planning-authority-input" />
      <Field label="Proposal" value={f.description} onChangeText={set("description")} placeholder="e.g. Outline for 4 detached dwellings" testID="planning-description-input" />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.md }}>
        {DATES.map((d) => (
          <View key={d.k} style={{ flexBasis: "45%", flexGrow: 1 }}>
            <Field label={d.l} value={f[d.k]} onChangeText={set(d.k)} placeholder="YYYY-MM-DD" testID={`planning-${d.k}-input`} />
          </View>
        ))}
      </View>
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Decision</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {(Object.keys(DECISIONS) as PlanningApp["decision"][]).map((k) => (
            <Chip key={k} label={DECISIONS[k]} selected={f.decision === k} onPress={() => set("decision")(k)} testID={`planning-decision-chip-${k}`} />
          ))}
        </ScrollView>
      </View>
      {f.decision !== "pending" && <Field label="Decision date" value={f.decision_date} onChangeText={set("decision_date")} placeholder="YYYY-MM-DD" testID="planning-decision_date-input" />}
      <Field label="Notes" value={f.notes} onChangeText={set("notes")} multiline placeholder="Conditions, case officer, objections…" testID="planning-notes-input" />
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="planning-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
