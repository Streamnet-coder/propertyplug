import { useMutation, useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, fileUrl, gbp } from "@/src/api";
import { DesignHotspots } from "@/src/components/design-hotspots";
import { Button, Card, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { SavedEstimate } from "./ai-estimates";

/** Review a saved AI estimate: design image with price pins, items (add to budget), rename, set as project photo, delete. */
export default function EstimateView() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ["ai-estimate", id], queryFn: () => api<SavedEstimate>(`/ai/estimates/${id}`) });
  const [title, setTitle] = useState<string | null>(null);
  const [addedNow, setAdded] = useState<Record<number, boolean>>({});
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ai-estimates"] });

  const rename = useMutation({
    mutationFn: () => api<SavedEstimate>(`/ai/estimates/${id}`, { method: "PUT", body: { title: title ?? "" } }),
    onSuccess: (d) => { queryClient.setQueryData(["ai-estimate", id], d); refresh(); setTitle(null); toast("Name saved"); },
  });
  const cover = useMutation({
    mutationFn: (path: string) => api("/project/cover", { method: "PUT", body: { storage_path: path } }),
    onSuccess: () => { invalidate("project", "projects"); toast("Set as project photo"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const del = useMutation({
    mutationFn: () => api(`/ai/estimates/${id}`, { method: "DELETE" }),
    onSuccess: () => { refresh(); toast("Estimate deleted"); router.back(); },
  });
  const add = async (i: number) => {
    const it = q.data!.items[i];
    try {
      await api("/line-items", { body: { name: it.name, category: it.category === "Soft Cost" ? "Soft Cost" : "Hard Cost", budgeted: Math.round((it.low + it.high) / 2), actual: 0, supplier: it.supplier, status: "Planned" } });
      setAdded((a) => ({ ...a, [i]: true }));
      api(`/ai/estimates/${id}/added`, { body: { index: i } }).catch(() => {});
      invalidate("line-items", "project");
      toast("Added to budget");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const choose = useMutation({
    mutationFn: () => api<{ added: number; estimate: SavedEstimate }>(`/ai/estimates/${id}/choose`, { method: "POST" }),
    onSuccess: (r) => {
      queryClient.setQueryData(["ai-estimate", id], r.estimate);
      refresh();
      invalidate("line-items", "project");
      toast(r.added ? `Chosen · ${r.added} item${r.added === 1 ? "" : "s"} added to budget` : "Chosen · items were already in your budget");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const e = q.data;
  const added = (i: number) => !!addedNow[i] || !!e?.added_items?.includes(i);

  return (
    <FormScreen title="Saved estimate" testID="estimate-view-screen">
      {!e ? <ActivityIndicator color={colors.brand} /> : (
        <>
          {title === null ? (
            <View style={{ gap: 2 }}>
              <Text style={s.title} testID="estimate-view-title">{e.title || e.description}</Text>
              <Text style={s.muted}>{e.finish_type} · {e.created_at.slice(0, 10)}</Text>
              <Button small variant="ghost" icon="pencil" title="Rename" onPress={() => setTitle(e.title || "")} style={{ alignSelf: "flex-start" }} testID="estimate-rename" />
            </View>
          ) : (
            <View style={{ gap: space.sm }}>
              <Field label="Name" value={title} onChangeText={setTitle} placeholder="e.g. Kitchen option A" testID="estimate-title-input" />
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small variant="outline" title="Cancel" onPress={() => setTitle(null)} style={{ flex: 1 }} testID="estimate-title-cancel" />
                <Button small title="Save" loading={rename.isPending} onPress={() => rename.mutate()} style={{ flex: 1 }} testID="estimate-title-save" />
              </View>
            </View>
          )}
          <View style={s.total}>
            <Text style={s.totalLabel}>Estimated total</Text>
            <Text style={s.totalVal} testID="estimate-view-total">{gbp(e.total_low)} – {gbp(e.total_high)}</Text>
          </View>
          {e.title ? <Text style={s.muted}>{e.description}</Text> : null}
          {e.design_path ? (
            <>
              <Text style={s.label}>Finished look</Text>
              <DesignHotspots path={e.design_path} pins={e.pins} />
              <Button small variant="secondary" icon="image" title="Use as project photo" loading={cover.isPending} onPress={() => cover.mutate(e.design_path!)} testID="estimate-set-cover" />
            </>
          ) : null}
          {e.photo_path ? (
            <>
              <Text style={s.label}>Your original photo</Text>
              <Image source={{ uri: fileUrl(e.photo_path) }} style={s.photo} contentFit="cover" testID="estimate-view-photo" />
            </>
          ) : null}
          {e.chosen ? (
            <View style={s.chosenBox} testID="estimate-chosen-badge">
              <Icon name="circle-check" size={18} color={colors.success} />
              <Text style={[s.itemName, { flex: 1 }]}>Chosen option{e.chosen_at ? ` · ${e.chosen_at.slice(0, 10)}` : ""}</Text>
            </View>
          ) : null}
          <Button icon="trophy" title={e.chosen ? "Add any missing items to budget" : "Choose this option & add all to budget"} loading={choose.isPending}
            disabled={e.chosen && e.items.every((_, i) => added(i))} onPress={() => choose.mutate()} testID="estimate-choose" />
          <Text style={s.label}>Items</Text>
          {e.items.map((it, i) => (
            <Card key={i} style={s.item} testID={`estimate-view-item-${i}`}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.itemName}>{it.name}</Text>
                {it.spec ? <Text style={s.muted} numberOfLines={2}>{it.spec}</Text> : null}
                <Text style={s.muted}>{it.supplier} · {it.category}</Text>
                <Text style={s.range}>{gbp(it.low)} – {gbp(it.high)}</Text>
              </View>
              <Button small variant={added(i) ? "outline" : "secondary"} icon={added(i) ? "check" : "plus"} title={added(i) ? "Added" : "Add"} disabled={added(i)} onPress={() => add(i)} testID={`estimate-view-add-${i}`} />
            </Card>
          ))}
          {e.notes ? (
            <View style={s.notes}>
              <Icon name="info" size={16} color={colors.brand} />
              <Text style={[s.muted, { flex: 1, lineHeight: 18 }]}>{e.notes}</Text>
            </View>
          ) : null}
          <Button small variant="ghost" icon="trash-2" title="Delete estimate" loading={del.isPending} onPress={() => del.mutate()} testID="estimate-delete" />
        </>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  total: { backgroundColor: c.brand, borderRadius: radius.lg, padding: space.lg },
  totalLabel: { fontFamily: fonts.medium, fontSize: 12, color: c.onBrand, opacity: 0.85 },
  totalVal: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onBrand, marginTop: 2 },
  photo: { width: "100%", height: 200, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  item: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md },
  itemName: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  range: { fontFamily: fonts.bold, fontSize: 14, color: c.brand, marginTop: 2 },
  chosenBox: { flexDirection: "row", alignItems: "center", gap: space.sm, backgroundColor: c.surfaceTertiary, padding: space.md, borderRadius: radius.md },
  notes: { flexDirection: "row", gap: space.sm, backgroundColor: c.brandTertiary, padding: space.md, borderRadius: radius.md },
}));
