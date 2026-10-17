import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { api } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate, useRentals } from "@/src/queries";
import { EXPENSE_CATEGORIES, ExpenseCategory, today } from "@/src/rentals";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function RentalExpenseForm() {
  const { id, year } = useLocalSearchParams<{ id?: string; year?: string }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data } = useRentals(Number(year) || new Date().getFullYear());
  const existing = data?.expenses.find((e) => e.id === id);
  const [f, setF] = useState({ category: "repairs" as ExpenseCategory, amount: "", date: today(), description: "" });
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (existing) setF({ category: existing.category as ExpenseCategory, amount: String(existing.amount), date: existing.date, description: existing.description });
  }, [existing]);

  const done = async (msg: string) => {
    await invalidate("rentals");
    toast(msg);
    router.back();
  };
  const save = useMutation({
    mutationFn: () => api(id ? `/rentals/expenses/${id}` : "/rentals/expenses", { method: id ? "PUT" : "POST", body: { ...f, amount: Number(f.amount), date: f.date.trim() } }),
    onSuccess: () => done(id ? "Expense updated" : "Expense added"),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({ mutationFn: () => api(`/rentals/expenses/${id}`, { method: "DELETE" }), onSuccess: () => done("Expense removed") });

  const submit = () => {
    setError("");
    if (!(Number(f.amount) > 0)) return setError("Enter the amount");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date.trim())) return setError("Use date format YYYY-MM-DD");
    save.mutate();
  };

  return (
    <FormScreen
      title={id ? "Edit expense" : "New property expense"}
      testID="rental-expense-form-screen"
      footer={
        <>
          <Button title={id ? "Save expense" : "Add expense"} loading={save.isPending} onPress={submit} testID="rental-expense-save-button" />
          {id && <Button variant="danger" icon="trash-2" title="Delete expense" loading={remove.isPending} onPress={() => remove.mutate()} testID="rental-expense-delete-button" />}
        </>
      }
    >
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Category</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
          {(Object.keys(EXPENSE_CATEGORIES) as ExpenseCategory[]).map((k) => (
            <Chip key={k} label={EXPENSE_CATEGORIES[k]} selected={f.category === k} onPress={() => set("category")(k)} testID={`rental-expense-cat-${k}`} />
          ))}
        </View>
      </View>
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}><Field label="Amount" value={f.amount} onChangeText={set("amount")} keyboardType="decimal-pad" placeholder="120" testID="rental-expense-amount-input" /></View>
        <View style={{ flex: 1 }}><Field label="Date" value={f.date} onChangeText={set("date")} placeholder="YYYY-MM-DD" testID="rental-expense-date-input" /></View>
      </View>
      <Field label="Description" value={f.description} onChangeText={set("description")} placeholder="e.g. Boiler service" testID="rental-expense-description-input" />
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="rental-expense-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
