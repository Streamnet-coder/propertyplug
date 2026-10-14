import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, Category, LineItem } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate, useLineItems } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const CATS: Category[] = ["Hard Cost", "Soft Cost", "Contingency"];
const STATUSES = ["Planned", "Quoted", "Purchased", "In Progress", "Paid"];

export default function ItemForm() {
  const { id, name: preName, budgeted: preBudget, supplier: preSupplier, category: preCat } = useLocalSearchParams<{
    id?: string;
    name?: string;
    budgeted?: string;
    supplier?: string;
    category?: string;
  }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const items = useLineItems();
  const existing = items.data?.find((i) => i.id === id);

  const [name, setName] = useState(preName ?? "");
  const [category, setCategory] = useState<Category>((preCat as Category) || "Hard Cost");
  const [budgeted, setBudgeted] = useState(preBudget ?? "");
  const [actual, setActual] = useState("");
  const [supplier, setSupplier] = useState(preSupplier ?? "");
  const [status, setStatus] = useState("Planned");
  const [error, setError] = useState("");

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      setCategory(existing.category);
      setBudgeted(String(existing.budgeted));
      setActual(String(existing.actual));
      setSupplier(existing.supplier);
      setStatus(existing.status);
    }
  }, [existing]);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), category, budgeted: Number(budgeted) || 0, actual: Number(actual) || 0, supplier, status };
      return id ? api<LineItem>(`/line-items/${id}`, { method: "PUT", body }) : api<LineItem>("/line-items", { body });
    },
    onSuccess: async () => {
      await invalidate("line-items", "project");
      toast(id ? "Line item updated" : "Line item added");
      router.back();
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: () => api(`/line-items/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidate("line-items", "project");
      toast("Line item deleted");
      router.back();
    },
  });

  return (
    <FormScreen
      title={id ? "Edit line item" : "New line item"}
      testID="item-form-screen"
      footer={
        <>
          <Button
            title={id ? "Save changes" : "Add to budget"}
            loading={save.isPending}
            onPress={() => (name.trim() ? save.mutate() : setError("Please enter a name"))}
            testID="item-form-save-button"
          />
          {id && <Button variant="danger" title="Delete item" icon="trash-2" loading={remove.isPending} onPress={() => remove.mutate()} testID="item-form-delete-button" />}
        </>
      }
    >
      <Field label="Item name" value={name} onChangeText={setName} placeholder="e.g. Kitchen units & worktop" testID="item-name-input" />
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Category</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {CATS.map((c) => (
            <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(c)} testID={`item-category-${c.replace(" ", "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}>
          <Field label="Budgeted (£)" value={budgeted} onChangeText={setBudgeted} keyboardType="decimal-pad" placeholder="0" testID="item-budgeted-input" />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="Actual (£)" value={actual} onChangeText={setActual} keyboardType="decimal-pad" placeholder="0" testID="item-actual-input" />
        </View>
      </View>
      <Field label="Supplier" value={supplier} onChangeText={setSupplier} placeholder="B&Q, Wickes, Toolstation…" testID="item-supplier-input" />
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Status</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {STATUSES.map((st) => (
            <Chip key={st} label={st} selected={status === st} onPress={() => setStatus(st)} testID={`item-status-${st.replace(" ", "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="item-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
