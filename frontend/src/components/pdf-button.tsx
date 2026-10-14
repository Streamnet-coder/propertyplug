import { useState } from "react";
import { ActivityIndicator, Pressable } from "react-native";

import { Icon, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

/** Round header button that generates a PDF via the given async function. */
export function PdfButton({ onGenerate, testID }: { onGenerate: () => Promise<void>; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    tap();
    setBusy(true);
    try {
      await onGenerate();
    } catch (e: any) {
      toast(e?.message ?? "Couldn't create the PDF", "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Pressable testID={testID} onPress={run} disabled={busy} style={s.btn} hitSlop={8} accessibilityLabel="Download PDF">
      {busy ? <ActivityIndicator size="small" color={colors.brand} /> : <Icon name="file-down" size={20} color={colors.brand} />}
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  btn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
}));
