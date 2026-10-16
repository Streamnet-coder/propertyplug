import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, sym } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadAsset } from "@/src/upload";

const CATS = ["Hard Cost", "Soft Cost", "Contingency"];
const today = () => new Date().toISOString().slice(0, 10);

export default function ReceiptForm() {
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [supplier, setSupplier] = useState("");
  const [date, setDate] = useState(today());
  const [category, setCategory] = useState("Hard Cost");
  const [photo, setPhoto] = useState<PickedAsset | null>(null);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: async () => {
      const storage_path = photo ? await uploadAsset(photo) : null;
      return api("/receipts", { body: { title: title.trim(), amount: Number(amount), supplier, date, category, storage_path } });
    },
    onSuccess: async () => {
      await invalidate("receipts", "project");
      toast("Expense saved");
      router.back();
    },
    onError: (e: Error) => setError(e.message),
  });

  const submit = () => {
    setError("");
    if (!title.trim()) return setError("Please add a title");
    if (!(Number(amount) > 0)) return setError("Please enter a valid amount");
    save.mutate();
  };

  return (
    <FormScreen title="Add expense / receipt" testID="receipt-form-screen" footer={<Button title="Save expense" loading={save.isPending} onPress={submit} testID="receipt-form-save-button" />}>
      <PhotoPicker value={photo} onChange={setPhoto} hint="Snap or upload the receipt (optional). We'll ask for camera/photo access only when you tap." />
      <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Toolstation cable & sockets" testID="receipt-title-input" />
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}>
          <Field label={`Amount (${sym()})`} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0.00" testID="receipt-amount-input" />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="Date" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" testID="receipt-date-input" />
        </View>
      </View>
      <Field label="Supplier" value={supplier} onChangeText={setSupplier} placeholder="B&Q, Wickes, Wren Kitchens…" testID="receipt-supplier-input" />
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Cost category</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {CATS.map((c) => (
            <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(c)} testID={`receipt-category-${c.replace(" ", "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="receipt-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
