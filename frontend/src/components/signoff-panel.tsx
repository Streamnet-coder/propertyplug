import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Snag, SnagSignoff } from "@/src/api";
import { useAuth } from "@/src/auth";
import { RatingSheet, Stars, useProjectRatings } from "@/src/components/rating";
import { SignaturePad, SignatureValue, SignatureView } from "@/src/components/signature-pad";
import { Button, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export const useSignoffs = () => useQuery({ queryKey: ["snag-signoffs"], queryFn: () => api<SnagSignoff[]>("/snag-signoffs") });

const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Per-trade sign-off status cards shown above the snag list. */
export function SignoffPanel({ snags }: { snags: Snag[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useSignoffs();
  const [signing, setSigning] = useState<string | null>(null);
  const [rating, setRating] = useState<string | null>(null);
  const ratings = useProjectRatings();
  const ratingFor = (n: string) => ratings.data?.find((x) => x.assignee.toLowerCase() === n.toLowerCase());
  const groups = Object.values(
    snags.filter((x) => x.assignee.trim()).reduce<Record<string, { name: string; open: number; total: number }>>((a, x) => {
      const k = x.assignee.trim().toLowerCase();
      a[k] = a[k] ?? { name: x.assignee.trim(), open: 0, total: 0 };
      a[k].total += 1;
      if (x.status === "open") a[k].open += 1;
      return a;
    }, {}),
  );
  if (!groups.length) return null;
  const find = (n: string) => q.data?.find((x) => x.assignee.toLowerCase() === n.toLowerCase());

  return (
    <View style={{ gap: space.sm, marginBottom: space.sm }} testID="signoff-panel">
      <Text style={s.section}>Sign-off by trade</Text>
      {groups.map((g) => {
        const so = find(g.name);
        const slug = g.name.replace(/\s+/g, "-").toLowerCase();
        const state = g.open ? "open" : so?.complete ? "complete" : "ready";
        return (
          <View key={g.name} style={[s.card, state === "complete" && { borderColor: colors.success }]} testID={`signoff-${slug}`}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
              <View style={[s.icon, state === "complete" && { backgroundColor: colors.success }]}>
                <Icon name={state === "complete" ? "badge-check" : "signature"} size={18} color={state === "complete" ? colors.onSuccess : colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.name}>{g.name}</Text>
                <Text style={s.muted} testID={`signoff-status-${slug}`}>
                  {state === "open" ? `${g.open} snag${g.open === 1 ? "" : "s"} still open` : state === "complete" ? `Signed off by both · ${g.total} snags` : `All ${g.total} fixed · ${so?.owner ? "waiting for trade to sign" : so?.trade ? "trade signed, your signature needed" : "ready to sign off"}`}
                </Text>
              </View>
              {state === "ready" && !so?.owner && (
                <Button small icon="pen-line" title="Sign" onPress={() => { tap(); setSigning(g.name); }} testID={`signoff-sign-${slug}`} />
              )}
            </View>
            {(so?.owner || so?.trade) && (
              <View style={s.sigRow}>
                {[["Trade", so.trade], ["Owner", so.owner]].map(([label, sig]) =>
                  sig && typeof sig === "object" ? (
                    <View key={label as string} style={s.sigBox}>
                      <SignatureView sig={sig} height={40} />
                      <Text style={s.muted} numberOfLines={1}>{sig.name} · {label as string}</Text>
                      <Text style={s.muted}>{fmt(sig.signed_at)}</Text>
                    </View>
                  ) : (
                    <View key={label as string} style={[s.sigBox, { justifyContent: "center" }]}>
                      <Text style={s.muted}>{label as string}: not signed yet</Text>
                    </View>
                  ),
                )}
              </View>
            )}
            {state === "ready" && so?.owner && !so.trade && <Text style={s.muted}>Send {g.name} their snag link: they can sign at the bottom of the page.</Text>}
            {!g.open && so?.owner && (
              ratingFor(g.name) ? (
                <Pressable onPress={() => { tap(); setRating(g.name); }} style={s.rated} testID={`rating-show-${slug}`}>
                  <Stars value={ratingFor(g.name)!.stars} />
                  <Text style={[s.muted, { flex: 1 }]} numberOfLines={1}>{ratingFor(g.name)!.comment || ratingFor(g.name)!.tags.join(" · ") || "Your rating"}</Text>
                  <Text style={[s.muted, { color: colors.brand }]}>Edit</Text>
                </Pressable>
              ) : (
                <Button small variant="secondary" icon="star" title={`Rate ${g.name}`} onPress={() => { tap(); setRating(g.name); }} testID={`rating-open-${slug}`} />
              )
            )}
          </View>
        );
      })}
      <SignSheet assignee={signing} onClose={() => setSigning(null)} />
      <RatingSheet assignee={rating} existing={rating ? ratingFor(rating) : undefined} onClose={() => setRating(null)} />
    </View>
  );
}

function SignSheet({ assignee, onClose }: { assignee: string | null; onClose: () => void }) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [sig, setSig] = useState<SignatureValue | null>(null);
  useEffect(() => { if (assignee) { setName(user?.name ?? ""); setSig(null); } }, [assignee, user?.name]);

  const save = useMutation({
    mutationFn: () => api<SnagSignoff>("/snag-signoffs", { body: { assignee, name, ...sig } }),
    onSuccess: (d) => {
      queryClient.setQueryData<SnagSignoff[]>(["snag-signoffs"], (old = []) => [...old.filter((x) => x.assignee.toLowerCase() !== d.assignee.toLowerCase()), d]);
      toast(d.complete ? "Snag list fully signed off" : "Signed. Now ask the trade to sign on their link");
      onClose();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <Modal visible={!!assignee} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="signoff-sheet">
          <ScrollView scrollEnabled={false} contentContainerStyle={{ gap: space.md }}>
            <Text style={s.title}>Sign off {assignee}&apos;s snags</Text>
            <Text style={s.muted}>By signing you confirm all snags assigned to {assignee} are fixed to your satisfaction.</Text>
            <Field label="Your name" value={name} onChangeText={setName} testID="signoff-name-input" />
            <SignaturePad onChange={setSig} testID="signoff-pad" />
            <Button icon="badge-check" title="Confirm sign-off" disabled={!sig || !name.trim()} loading={save.isPending} onPress={() => save.mutate()} testID="signoff-confirm" />
            <Button variant="outline" title="Cancel" onPress={onClose} testID="signoff-cancel" />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  section: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  card: { backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md, gap: space.sm },
  icon: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  rated: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.sm, borderRadius: radius.sm, backgroundColor: c.surfaceSecondary, minHeight: 44 },
  sigRow: { flexDirection: "row", gap: space.sm },
  sigBox: { flex: 1, padding: space.sm, borderRadius: radius.sm, backgroundColor: c.surfaceSecondary, minHeight: 80, gap: 2 },
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
}));
