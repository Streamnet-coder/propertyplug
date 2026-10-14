import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate, useProject } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const FINISHES = ["Basic Finish", "Medium Finish", "High Finish"];

export default function ProjectEdit() {
  const { mode } = useLocalSearchParams<{ mode?: string }>();
  const isNew = mode === "new";
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data: p } = useProject();
  const [f, setF] = useState({ name: "", address: "", purchase_price: "", estimated_valuation: "", monthly_rent: "", hard: "", soft: "", contingency: "", finish_type: "Medium Finish" });
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (p && !isNew)
      setF({
        name: p.name,
        address: p.address,
        purchase_price: String(p.purchase_price),
        estimated_valuation: String(p.estimated_valuation),
        monthly_rent: String(p.monthly_rent),
        hard: String(p.budget.hard),
        soft: String(p.budget.soft),
        contingency: String(p.budget.contingency),
        finish_type: p.finish_type,
      });
  }, [p, isNew]);

  const save = useMutation({
    mutationFn: () =>
      api(isNew ? "/projects" : "/project", {
        method: isNew ? "POST" : "PUT",
        body: {
          name: f.name,
          address: f.address,
          finish_type: f.finish_type,
          purchase_price: Number(f.purchase_price) || 0,
          estimated_valuation: Number(f.estimated_valuation) || 0,
          monthly_rent: Number(f.monthly_rent) || 0,
          budget: { hard: Number(f.hard) || 0, soft: Number(f.soft) || 0, contingency: Number(f.contingency) || 0 },
        },
      }),
    onSuccess: async () => {
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
  return (
    <FormScreen
      title={isNew ? "New project" : "Edit project"}
      testID="project-edit-screen"
      footer={<Button title={isNew ? "Create project" : "Save project"} loading={save.isPending} onPress={() => (f.name.trim() ? save.mutate() : toast("Please enter a project name", "error"))} testID="project-save-button" />}
    >
      <Field label="Project name" value={f.name} onChangeText={set("name")} placeholder="e.g. Derby terrace flip" testID="project-name-input" />
      <Field label="Address" value={f.address} onChangeText={set("address")} placeholder="Street, town, postcode" testID="project-address-input" />
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label="Purchase (£)" value={f.purchase_price} onChangeText={set("purchase_price")} {...num} testID="project-purchase-input" /></View>
        <View style={{ flex: 1 }}><Field label="Valuation (£)" value={f.estimated_valuation} onChangeText={set("estimated_valuation")} {...num} testID="project-valuation-input" /></View>
      </View>
      <Field label="Expected monthly rent (£)" value={f.monthly_rent} onChangeText={set("monthly_rent")} {...num} testID="project-rent-input" />
      <Text style={{ fontFamily: fonts.bold, fontSize: 16, color: colors.onSurface, marginTop: space.sm }}>Budget</Text>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label="Hard (£)" value={f.hard} onChangeText={set("hard")} {...num} testID="project-hard-input" /></View>
        <View style={{ flex: 1 }}><Field label="Soft (£)" value={f.soft} onChangeText={set("soft")} {...num} testID="project-soft-input" /></View>
        <View style={{ flex: 1 }}><Field label="Contingency" value={f.contingency} onChangeText={set("contingency")} {...num} testID="project-contingency-input" /></View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        {FINISHES.map((x) => (
          <Chip key={x} label={x} selected={f.finish_type === x} onPress={() => set("finish_type")(x)} testID={`project-finish-${x.split(" ")[0].toLowerCase()}`} />
        ))}
      </ScrollView>
    </FormScreen>
  );
}
