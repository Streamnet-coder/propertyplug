import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, gbp } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, useLineItems, useShopping } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function ShoppingAdd() {
  const router = useRouter();
  const toast = useToast();
  const s = useStyles();
  const { colors } = useTheme();
  const [mode, setMode] = useState<"budget" | "custom">("budget");
  const [picked, setPicked] = useState<string[]>([]);
  const [f, setF] = useState({ name: "", supplier: "", qty: "", est_cost: "" });
  const items = useLineItems();
  const shop = useShopping();
  const onList = new Set((shop.data ?? []).map((x) => x.line_item_id).filter(Boolean));
  const avail = (items.data ?? []).filter((i) => !onList.has(i.id));

  const save = useMutation({
    mutationFn: () =>
      mode === "budget"
        ? api<{ added: number }>("/shopping/from-line-items", { body: { line_item_ids: picked } })
        : api("/shopping", { body: { ...f, est_cost: Number(f.est_cost) || 0 } }),
    onSuccess: async (d: any) => {
      await invalidate("shopping");
      toast(mode === "budget" ? `Added ${d.added} item${d.added === 1 ? "" : "s"} to your list` : "Item added");
      router.back();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const canSave = mode === "budget" ? picked.length > 0 : !!f.name.trim();
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  return (
    <FormScreen
      title="Add to list"
      testID="shopping-add-screen"
      footer={<Button title={mode === "budget" ? `Add ${picked.length || ""} selected`.replace("  ", " ") : "Add item"} disabled={!canSave} loading={save.isPending} onPress={() => save.mutate()} testID="shopping-add-save" />}
    >
      <View style={{ flexDirection: "row", gap: space.sm }}>
        <Chip label="From budget" icon="clipboard-list" selected={mode === "budget"} onPress={() => setMode("budget")} testID="shopping-mode-budget" />
        <Chip label="One-off item" icon="plus" selected={mode === "custom"} onPress={() => setMode("custom")} testID="shopping-mode-custom" />
      </View>
      {mode === "budget" ? (
        items.isLoading ? (
          <ActivityIndicator color={colors.brand} />
        ) : avail.length === 0 ? (
          <Text style={s.muted} testID="shopping-add-none">All your budget items are already on the list.</Text>
        ) : (
          <View style={{ gap: space.sm }}>
            <Pressable onPress={() => setPicked(picked.length === avail.length ? [] : avail.map((i) => i.id))} testID="shopping-select-all" hitSlop={8}>
              <Text style={s.link}>{picked.length === avail.length ? "Clear selection" : "Select all"}</Text>
            </Pressable>
            {avail.map((i) => {
              const on = picked.includes(i.id);
              return (
                <Pressable
                  key={i.id}
                  testID={`shopping-pick-${i.id}`}
                  onPress={() => { tap(); setPicked((p) => (on ? p.filter((x) => x !== i.id) : [...p, i.id])); }}
                  style={[s.row, on && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]}
                >
                  <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>
                    {on && <Icon name="check" size={14} color={colors.onBrand} />}
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.name}>{i.name}</Text>
                    <Text style={s.muted}>{i.supplier || "No supplier"} · {i.status}</Text>
                  </View>
                  <Text style={s.amt}>{gbp(i.budgeted)}</Text>
                </Pressable>
              );
            })}
          </View>
        )
      ) : (
        <>
          <Field label="Item" value={f.name} onChangeText={set("name")} placeholder="e.g. 25kg multi-finish plaster" testID="shopping-name-input" />
          <Field label="Merchant" value={f.supplier} onChangeText={set("supplier")} placeholder="e.g. Screwfix" testID="shopping-supplier-input" />
          <View style={{ flexDirection: "row", gap: space.md }}>
            <View style={{ flex: 1 }}><Field label="Quantity" value={f.qty} onChangeText={set("qty")} placeholder="e.g. 4 bags" testID="shopping-qty-input" /></View>
            <View style={{ flex: 1 }}><Field label="Est. cost (£)" value={f.est_cost} onChangeText={set("est_cost")} keyboardType="decimal-pad" testID="shopping-cost-input" /></View>
          </View>
        </>
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  link: { fontFamily: fonts.semibold, fontSize: 14, color: c.brand },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface, minHeight: 60 },
  box: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  amt: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
}));
