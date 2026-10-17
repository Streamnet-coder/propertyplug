import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";

import { api, Estimate, gbp } from "@/src/api";
import { DesignHotspots, DesignPin } from "@/src/components/design-hotspots";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { uploadAsset } from "@/src/upload";
import { Button, Card, Chip, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { useRouter } from "expo-router";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const FINISHES = ["Basic Finish", "Medium Finish", "High Finish"];
const EXAMPLES = ["Full kitchen refit, 3m x 4m, new units & laminate worktop", "Re-plaster and paint two bedrooms", "Replace bathroom suite with shower over bath"];

export default function AiEstimate() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const [desc, setDesc] = useState("");
  const [finish, setFinish] = useState("Medium Finish");
  const [added, setAdded] = useState<Record<number, boolean>>({});
  const [photo, setPhoto] = useState<PickedAsset | null>(null);

  const design = useMutation({
    mutationFn: (id: string) => api<{ image_path: string; pins: DesignPin[] }>(`/ai/estimate/${id}/design`, { method: "POST" }),
    onSuccess: () => { invalidate("media"); queryClient.invalidateQueries({ queryKey: ["ai-estimates"] }); toast("Design saved to your photos and Saved estimates"); },
  });
  const est = useMutation({
    mutationFn: async () => {
      const photo_path = photo ? await uploadAsset(photo) : undefined;
      return api<Estimate & { id: string }>("/ai/estimate", { body: { description: desc, finish_type: finish, photo_path } });
    },
    onSuccess: (d) => { setAdded({}); design.reset(); design.mutate(d.id); }, // design the finished look straight after the estimate
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
      <Button small variant="outline" icon="bookmark" title="Saved estimates" onPress={() => router.push("/ai-estimates")} testID="ai-estimate-saved-link" />
      <Field label="Describe the work" value={desc} onChangeText={setDesc} multiline placeholder="e.g. New kitchen with 8 units, quartz worktop, tiling…" testID="ai-estimate-description-input" />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        {EXAMPLES.map((e, i) => (
          <Chip key={e} label={e.length > 28 ? e.slice(0, 28) + "…" : e} onPress={() => setDesc(e)} testID={`ai-example-${i}`} />
        ))}
      </ScrollView>
      <PhotoPicker value={photo} onChange={setPhoto} hint="Add a photo of the space (optional). The AI uses it for the estimate and designs the finished look over it." />
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
          <Text style={s.muted}>{photo ? "Uploading your photo, then checking" : "Checking"} UK supplier prices and trade rates…</Text>
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
          <Text style={s.label}>Finished look</Text>
          {design.isPending && (
            <Card style={{ alignItems: "center", gap: space.sm }} testID="design-loading">
              <Icon name="wand-sparkles" size={22} color={colors.brandPrimary} />
              <Text style={s.muted}>Designing your finished {photo ? "room from your photo" : "space"} and pinning prices… (about 20 seconds)</Text>
            </Card>
          )}
          {design.isError && (
            <Card style={{ gap: space.sm }} testID="design-error">
              <Text style={{ color: colors.error, fontFamily: fonts.medium }}>{(design.error as Error).message}</Text>
              <Button small variant="outline" icon="refresh-cw" title="Try the design again" onPress={() => design.mutate(est.data!.id)} testID="design-retry-button" />
            </Card>
          )}
          {design.data && <DesignHotspots path={design.data.image_path} pins={design.data.pins} />}
          <Text style={s.label}>Items</Text>
          {est.data.items.map((it, i) => (
            <Card key={i} style={s.item}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.itemName}>{it.name}</Text>
                {it.spec ? <Text style={s.muted} numberOfLines={2}>{it.spec}</Text> : null}
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
