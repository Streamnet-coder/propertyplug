import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, TradeRating, TrustedTrade } from "@/src/api";
import { Button, Chip, Field, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export const RATING_TAGS = ["Quality work", "On time", "Tidy", "Good value", "Communicative", "Would hire again"];
export const useProjectRatings = () => useQuery({ queryKey: ["trade-ratings", "active"], queryFn: () => api<TradeRating[]>("/trade-ratings?project=active") });
export const useTrustedTrades = () => useQuery({ queryKey: ["trusted-trades"], queryFn: () => api<TrustedTrade[]>("/trusted-trades") });

export function Stars({ value, size = 14, testID }: { value: number; size?: number; testID?: string }) {
  const { colors } = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: 1 }} testID={testID}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Icon key={i} name="star" size={size} color={i <= Math.round(value) ? colors.brandPrimary : colors.borderStrong} />
      ))}
    </View>
  );
}

export function RatingSheet({ assignee, existing, onClose }: { assignee: string | null; existing?: TradeRating; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [stars, setStars] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  useEffect(() => {
    if (assignee) { setStars(existing?.stars ?? 0); setTags(existing?.tags ?? []); setComment(existing?.comment ?? ""); }
  }, [assignee, existing]);

  const save = useMutation({
    mutationFn: () => api<TradeRating>("/trade-ratings", { body: { assignee, stars, tags, comment } }),
    onSuccess: () => { invalidate("trade-ratings", "trusted-trades"); toast(`Rated ${assignee} ${stars}★`); onClose(); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <Modal visible={!!assignee} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="rating-sheet">
          <Text style={s.title}>Rate {assignee}</Text>
          <Text style={s.muted}>Your private rating builds a trusted trades list you can reuse on every project.</Text>
          <View style={s.starRow}>
            {[1, 2, 3, 4, 5].map((i) => (
              <Pressable key={i} onPress={() => { tap(); setStars(i); }} hitSlop={6} style={s.starBtn} testID={`rating-star-${i}`} accessibilityLabel={`${i} star${i > 1 ? "s" : ""}`}>
                <Icon name="star" size={32} color={i <= stars ? colors.brandPrimary : colors.borderStrong} />
              </Pressable>
            ))}
          </View>
          <View style={s.tags}>
            {RATING_TAGS.map((t) => (
              <Chip key={t} label={t} selected={tags.includes(t)} onPress={() => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))} testID={`rating-tag-${t.replace(/\s+/g, "-").toLowerCase()}`} />
            ))}
          </View>
          <Field label="Comment (optional)" value={comment} onChangeText={setComment} placeholder="e.g. Neat work, turned up every day at 8" multiline testID="rating-comment-input" />
          <Button icon="star" title={stars ? `Save ${stars}-star rating` : "Choose a rating"} disabled={!stars} loading={save.isPending} onPress={() => save.mutate()} testID="rating-save" />
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
  starRow: { flexDirection: "row", justifyContent: "center", gap: space.xs },
  starBtn: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
}));
