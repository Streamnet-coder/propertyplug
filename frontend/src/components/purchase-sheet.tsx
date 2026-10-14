import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, ShoppingItem } from "@/src/api";
import { Button, Field, fonts, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles } from "@/src/theme";
import { useToast } from "@/src/toast";

export function PurchaseSheet({ item, onClose }: { item: ShoppingItem | null; onClose: () => void }) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  useEffect(() => { if (item) setAmount(item.est_cost ? String(item.est_cost) : ""); }, [item]);

  const done = () => { invalidate("shopping", "receipts", "project", "digest"); onClose(); };
  const log = useMutation({
    mutationFn: () => api(`/shopping/${item!.id}/purchase`, { body: { amount: Number(amount) } }),
    onSuccess: () => { toast(`Logged ${gbp(Number(amount), 2)} against your budget`); done(); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const justTick = useMutation({
    mutationFn: () => api(`/shopping/${item!.id}`, { method: "PUT", body: { checked: true } }),
    onSuccess: done,
  });
  const valid = Number(amount) > 0;

  return (
    <Modal visible={!!item} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="purchase-sheet">
          <Text style={s.title}>Bought {item?.name}?</Text>
          <Text style={s.muted}>Log what you actually paid{item?.supplier ? ` at ${item.supplier}` : ""}. It&apos;s saved as a receipt and counted in your budget spend.</Text>
          <Field label="Price paid (£)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" autoFocus testID="purchase-amount-input" />
          {item?.est_cost ? <Text style={s.muted}>Estimated {gbp(item.est_cost, 2)}</Text> : null}
          <Button title={valid ? `Log ${gbp(Number(amount), 2)} & tick off` : "Log price & tick off"} icon="receipt" disabled={!valid} loading={log.isPending} onPress={() => log.mutate()} testID="purchase-log-button" />
          <Button variant="outline" title="Just tick it off" loading={justTick.isPending} onPress={() => justTick.mutate()} testID="purchase-skip-button" />
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
