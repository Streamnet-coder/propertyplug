import { useQuery } from "@tanstack/react-query";
import * as WebBrowser from "expo-web-browser";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, BillingItem, receiptUrl } from "@/src/api";
import { EmptyState, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const money = (n: number, cur: string) => `${cur === "GBP" ? "£" : `${cur} `}${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function Billing() {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["billing-history"], queryFn: () => api<BillingItem[]>("/payments/history") });
  const open = (b: BillingItem) => { tap(); WebBrowser.openBrowserAsync(b.receipt === "local" ? receiptUrl(b.id) : b.url!); };
  const tone = (st: BillingItem["status"]) => (st === "paid" ? colors.success : st === "failed" ? colors.error : colors.brandPrimary);

  return (
    <FormScreen title="Billing history" testID="billing-screen">
      <Text style={s.muted}>Your Pro payments. Tap one to open the receipt, then print or save it as a PDF.</Text>
      {q.isLoading ? (
        <ActivityIndicator color={colors.brand} />
      ) : q.isError ? (
        <Text style={s.muted} testID="billing-error">Couldn&apos;t load your payments. Pull back later.</Text>
      ) : !q.data?.length ? (
        <EmptyState icon="receipt" title="No payments yet" subtitle="Your Pro receipts will appear here." testID="billing-empty" />
      ) : (
        q.data.map((b) => (
          <Pressable key={b.id} onPress={() => open(b)} disabled={b.receipt === "stripe" && !b.url} style={({ pressed }) => [s.row, pressed && { opacity: 0.85 }]} testID={`billing-row-${b.id}`}>
            <View style={s.icon}><Icon name="receipt" size={18} color={colors.brand} /></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name} numberOfLines={1}>{b.description}</Text>
              <Text style={s.muted}>{new Date(b.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · <Text style={{ color: tone(b.status), fontFamily: fonts.semibold }}>{b.status === "paid" ? "Paid" : b.status === "failed" ? "Failed" : "Due"}</Text></Text>
            </View>
            <View style={{ alignItems: "flex-end", gap: 2 }}>
              <Text style={s.amount} testID={`billing-amount-${b.id}`}>{money(b.amount, b.currency)}</Text>
              <Text style={[s.muted, { color: colors.brand, fontFamily: fonts.semibold }]}>Receipt</Text>
            </View>
          </Pressable>
        ))
      )}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md, minHeight: 64 },
  icon: { width: 36, height: 36, borderRadius: 10, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  amount: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
}));
