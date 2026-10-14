import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";

import { api, Estimate, gbp } from "@/src/api";
import { Button, Card, Chip, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const FINISHES = ["Basic Finish", "Medium Finish", "High Finish"];
const EXAMPLES = ["Full kitchen refit, 3m x 4m, new units & laminate worktop", "Re-plaster and paint two bedrooms", "Replace bathroom suite with shower over bath"];

export default function AiEstimate() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [desc, setDesc] = useState("");
  const [finish, setFinish] = useState("Medium Finish");
  const [added, setAdded] = useState<Record<number, boolean>>({});

  const est = useMutation({
    mutationFn: () => api<Estimate>("/ai/estimate", { body: { description: desc, finish_type: finish } }),
    onSuccess: () => setAdded({}),
  });

  const addItem = async (i: number) => {
    const it = est.data!.items[i];
    try {
      await api("/line-items", {
        body: {
          name: it.name,
          category: it.category === "Soft Cost" ? "Soft Cost" : "Hard Cost",
          budgeted: Math.round((it.low + it.high) / 2),
          actual: 0,
          supplier: it.supplier,
          status: "Planned",
        },
      });
      setAdded((a) => ({ ...a, [i]: true }));
      invalidate("line-items", "project");
      toast("Added to budget");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <FormScreen
      title="AI cost estimate"
      testID="ai-estimate-screen"
      footer={<Button title="Generate estimate" icon="sparkles" loading={est.isPending} disabled={!desc.trim()} onPress={() => est.mutate()} testID="ai-estimate-generate-button" />}
    >
      <Field label="Describe the work" value={desc} onChangeText={setDesc} multiline placeholder="e.g. New kitchen with 8 units, quartz worktop, tiling…" testID="ai-estimate-description-input" />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        {EXAMPLES.map((e, i) => (
          <Chip key={e} label={e.length > 28 ? e.slice(0, 28) + "…" : e} onPress={() => setDesc(e)} testID={`ai-example-${i}`} />
        ))}
      </ScrollView>
      <View style={{ gap: space.sm }}>
        <Text style={s.label}>Finish level</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {FINISHES.map((f) => (
            <Chip key={f} label={f} selected={finish === f} onPress={() => setFinish(f)} testID={`ai-finish-${f.split(" ")[0].toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>

      {est.isPending && (
        <Card style={{ alignItems: "center", gap: space.sm }} testID="ai-estimate-loading">
          <Icon name="sparkles" size={22} color={colors.brand} />
          <Text style={s.muted}>Checking UK supplier prices and trade rates…</Text>
        </Card>
      )}
      {est.isError && <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="ai-estimate-error">{(est.error as Error).message}</Text>}

      {est.data && (
        <Animated.View entering={FadeInDown} style={{ gap: space.md }} testID="ai-estimate-result">
          <View style={s.total}>
            <Text style={s.totalLabel}>Estimated total</Text>
            <Text style={s.totalVal} testID="ai-estimate-total">
              {gbp(est.data.total_low)} – {gbp(est.data.total_high)}
            </Text>
          </View>
          {est.data.items.map((it, i) => (
            <Card key={i} style={s.item}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.itemName}>{it.name}</Text>
                <Text style={s.muted}>{it.supplier} · {it.category}</Text>
                <Text style={s.range}>{gbp(it.low)} – {gbp(it.high)}</Text>
              </View>
              <Button
                small
                variant={added[i] ? "outline" : "secondary"}
                icon={added[i] ? "check" : "plus"}
                title={added[i] ? "Added" : "Add"}
                disabled={added[i]}
                onPress={() => addItem(i)}
                testID={`ai-estimate-add-${i}`}
              />
            </Card>
          ))}
          {est.data.notes ? (
            <View style={s.notes}>
              <Icon name="info" size={16} color={colors.brand} />
              <Text style={[s.muted, { flex: 1, lineHeight: 18 }]}>{est.data.notes}</Text>
            </View>
          ) : null}
        </Animated.View>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  total: { backgroundColor: c.brand, borderRadius: radius.lg, padding: space.lg },
  totalLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  totalVal: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onBrand, marginTop: 2 },
  item: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md },
  itemName: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  range: { fontFamily: fonts.bold, fontSize: 14, color: c.brand, marginTop: 2 },
  notes: { flexDirection: "row", gap: space.sm, backgroundColor: c.brandTertiary, padding: space.md, borderRadius: radius.md },
}));
