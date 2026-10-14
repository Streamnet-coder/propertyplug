import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, gbp, QuoteEntry, QuoteRequest } from "@/src/api";
import { Button, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { invalidate, useProject, useQuote } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const STATUS_LABEL: Record<QuoteEntry["status"], string> = { requested: "Awaiting", received: "Received", accepted: "Accepted", declined: "Declined" };

export default function QuoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { data: project } = useProject();
  const q = useQuote(id);
  const [editing, setEditing] = useState<QuoteEntry | null>(null);
  const [amount, setAmount] = useState("");
  const [days, setDays] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const setData = (d: QuoteRequest) => {
    queryClient.setQueryData(["quotes", id], d);
    invalidate("quotes");
  };

  const update = useMutation({
    mutationFn: (p: { eid: string; body: Record<string, unknown> }) => api<QuoteRequest>(`/quotes/${id}/entries/${p.eid}`, { method: "PUT", body: p.body }),
    onSuccess: setData,
    onError: (e: Error) => toast(e.message, "error"),
  });
  const accept = useMutation({
    mutationFn: (eid: string) => api<QuoteRequest>(`/quotes/${id}/entries/${eid}/accept`, { body: { add_to_budget: true } }),
    onSuccess: (d) => {
      setData(d);
      invalidate("line-items", "project");
      toast("Quote accepted and added to your budget");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({
    mutationFn: () => api(`/quotes/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidate("quotes");
      toast("Quote request deleted");
      router.back();
    },
  });

  if (q.isLoading) return <View style={[s.root, s.center]}><ActivityIndicator color={colors.brand} /></View>;
  if (q.isError || !q.data)
    return (
      <View style={[s.root, s.center]}>
        <Text style={s.muted}>Could not load this request.</Text>
        <Button small title="Go back" onPress={() => router.back()} testID="quote-detail-back-error" />
      </View>
    );

  const r = q.data;
  const priced = r.quotes.filter((x) => x.amount != null);
  const amounts = priced.map((x) => x.amount!);
  const low = amounts.length ? Math.min(...amounts) : null;
  const high = amounts.length ? Math.max(...amounts) : null;
  const avg = amounts.length ? amounts.reduce((a, b) => a + b, 0) / amounts.length : null;
  const sorted = [...r.quotes].sort((a, b) => (a.amount ?? Infinity) - (b.amount ?? Infinity));
  const awarded = r.quotes.some((x) => x.status === "accepted");

  const message = (e: QuoteEntry) =>
    `Hi ${e.name}, could you quote for "${r.title}"${project?.address ? ` at ${project.address}` : ""}?\n\n${r.description}\n\nPlease send your price here (takes 1 minute): ${e.link}`;

  const send = async (e: QuoteEntry) => {
    const wa = e.phone.replace(/[^\d]/g, "").replace(/^0/, "44");
    try {
      if (wa) await Linking.openURL(`https://wa.me/${wa}?text=${encodeURIComponent(message(e))}`);
      else if (e.email) await Linking.openURL(`mailto:${e.email}?subject=${encodeURIComponent(`Quote request: ${r.title}`)}&body=${encodeURIComponent(message(e))}`);
      else await Share.share({ message: message(e) });
      if (!e.sent) update.mutate({ eid: e.id, body: { sent: true } });
    } catch {
      toast("Couldn't open messaging on this device", "error");
    }
  };

  const openEdit = (e: QuoteEntry) => {
    setEditing(e);
    setAmount(e.amount != null ? String(e.amount) : "");
    setDays(e.days != null ? String(e.days) : "");
    setNotes(e.notes);
  };
  const saveEdit = () => {
    const a = Number(amount);
    if (!(a > 0)) return toast("Enter a valid price", "error");
    update.mutate({ eid: editing!.id, body: { amount: a, days: days ? parseInt(days, 10) : null, notes } }, { onSuccess: () => setEditing(null) });
  };

  return (
    <View style={s.root} testID="quote-detail-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="quote-detail-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <Text style={s.headerTitle} numberOfLines={1}>Compare quotes</Text>
        <Pressable testID="quote-delete-button" onPress={() => setConfirmDelete(true)} style={s.back} hitSlop={10}>
          <Icon name="trash-2" size={20} color={colors.muted} />
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={{ paddingVertical: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xl }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
      >
        <View style={[s.job, { marginHorizontal: space.lg }]}>
          <Text style={s.jobTitle} testID="quote-detail-title">{r.title}</Text>
          <Text style={s.jobDesc}>{r.description}</Text>
        </View>

        <View style={[s.statsRow, { marginHorizontal: space.lg }]} testID="quote-stats">
          {[
            ["Quotes in", `${priced.length}/${r.quotes.length}`],
            ["Lowest", low != null ? gbp(low) : "–"],
            ["Average", avg != null ? gbp(avg) : "–"],
            ["Spread", low != null && high != null ? gbp(high - low) : "–"],
          ].map(([l, v]) => (
            <View key={l} style={s.stat}>
              <Text style={s.muted}>{l}</Text>
              <Text style={s.statVal}>{v}</Text>
            </View>
          ))}
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.md }}>
          {sorted.map((e, i) => {
            const isLow = e.amount != null && e.amount === low && priced.length > 1;
            const accepted = e.status === "accepted";
            return (
              <View key={e.id} style={[s.col, accepted && { borderColor: colors.success, borderWidth: 2 }, isLow && !awarded && { borderColor: colors.brand, borderWidth: 2 }]} testID={`quote-card-${i}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <View style={[s.pill, { backgroundColor: accepted ? colors.brandTertiary : e.status === "received" ? colors.orangeTint : colors.surfaceTertiary }]}>
                    <Text style={[s.pillText, { color: accepted ? colors.brand : e.status === "received" ? colors.brandPrimary : colors.muted }]}>{STATUS_LABEL[e.status]}</Text>
                  </View>
                  {isLow && <Text style={s.lowest}>LOWEST</Text>}
                </View>
                <Text style={s.name} numberOfLines={1}>{e.name}</Text>
                <Text style={s.muted} numberOfLines={1}>{e.role || "Trade"}</Text>
                <Text style={[s.price, e.amount == null && { color: colors.muted, fontSize: 16 }]} testID={`quote-price-${i}`}>
                  {e.amount != null ? gbp(e.amount) : "No price yet"}
                </Text>
                <Text style={s.muted}>{e.days != null ? `${e.days} working days` : "Timescale –"}</Text>
                <Text style={s.notes} numberOfLines={4}>{e.notes || (e.sent ? "Request sent. Waiting for reply." : "Not sent yet.")}</Text>
                <View style={{ gap: space.sm, marginTop: "auto" }}>
                  {e.status === "requested" && (
                    <Button small variant={e.sent ? "outline" : "secondary"} icon="send" title={e.sent ? "Resend" : "Send request"} onPress={() => { tap(); send(e); }} testID={`quote-send-${i}`} />
                  )}
                  {!accepted && e.status !== "declined" && (
                    <Button small variant="outline" icon="pencil" title={e.amount != null ? "Edit price" : "Enter price"} onPress={() => openEdit(e)} testID={`quote-enter-price-${i}`} />
                  )}
                  {e.amount != null && !accepted && (
                    <Button small icon="check" title="Accept" loading={accept.isPending && accept.variables === e.id} onPress={() => accept.mutate(e.id)} testID={`quote-accept-${i}`} />
                  )}
                  {accepted && (
                    <>
                      <View style={s.acceptedBox}>
                        <Icon name="badge-check" size={16} color={colors.success} />
                        <Text style={[s.muted, { color: colors.success, fontFamily: fonts.semibold }]}>Added to budget</Text>
                      </View>
                      <Button small variant="outline" icon="calendar-check" title="Payment schedule" onPress={() => router.push("/payments")} testID={`quote-payments-${i}`} />
                    </>
                  )}
                </View>
              </View>
            );
          })}
        </ScrollView>
        <Text style={[s.muted, { marginHorizontal: space.lg, textAlign: "center" }]}>
          Trades submit prices via their private link. This page refreshes automatically.
        </Text>
      </ScrollView>

      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.overlay}>
          <Pressable style={{ ...StyleFill }} onPress={() => setEditing(null)} />
          <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="quote-price-modal">
            <Text style={s.jobTitle}>Price from {editing?.name}</Text>
            <Field label="Total price (£)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0" testID="quote-amount-input" />
            <Field label="Working days" value={days} onChangeText={setDays} keyboardType="number-pad" placeholder="e.g. 5" testID="quote-days-input" />
            <Field label="Notes" value={notes} onChangeText={setNotes} placeholder="What's included" testID="quote-notes-input" />
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button variant="outline" title="Cancel" onPress={() => setEditing(null)} style={{ flex: 1 }} testID="quote-price-cancel" />
              <Button title="Save price" loading={update.isPending} onPress={saveEdit} style={{ flex: 1 }} testID="quote-price-save" />
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <Modal visible={confirmDelete} transparent animationType="fade" onRequestClose={() => setConfirmDelete(false)}>
        <View style={[s.overlay, { justifyContent: "center", padding: space.lg }]}>
          <View style={[s.sheet, { borderRadius: radius.lg }]} testID="quote-delete-modal">
            <Text style={s.jobTitle}>Delete this quote request?</Text>
            <Text style={s.muted}>Trades will no longer be able to open their quote links.</Text>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button variant="outline" title="Cancel" onPress={() => setConfirmDelete(false)} style={{ flex: 1 }} testID="quote-delete-cancel" />
              <Button variant="danger" title="Delete" loading={remove.isPending} onPress={() => remove.mutate()} style={{ flex: 1 }} testID="quote-delete-confirm" />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const StyleFill = { position: "absolute" as const, top: 0, left: 0, right: 0, bottom: 0 };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  center: { alignItems: "center", justifyContent: "center", gap: space.md },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    backgroundColor: c.surface,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  job: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.sm },
  jobTitle: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  jobDesc: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurfaceTertiary, lineHeight: 20 },
  statsRow: { flexDirection: "row", backgroundColor: c.brand, borderRadius: radius.lg, padding: space.md },
  stat: { flex: 1, gap: 2 },
  statVal: { fontFamily: fonts.extrabold, fontSize: 15, color: c.onBrand },
  col: {
    width: 230,
    minHeight: 330,
    backgroundColor: c.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: space.lg,
    gap: 6,
  },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.bold, fontSize: 10 },
  lowest: { fontFamily: fonts.extrabold, fontSize: 10, color: c.brand, letterSpacing: 0.6 },
  name: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface, marginTop: space.xs },
  price: { fontFamily: fonts.extrabold, fontSize: 26, color: c.onSurface, marginTop: space.sm, letterSpacing: -0.5 },
  notes: { fontFamily: fonts.regular, fontSize: 12, color: c.onSurfaceTertiary, lineHeight: 17, marginBottom: space.sm },
  acceptedBox: { flexDirection: "row", alignItems: "center", gap: 6, justifyContent: "center", minHeight: 40 },
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
}));
