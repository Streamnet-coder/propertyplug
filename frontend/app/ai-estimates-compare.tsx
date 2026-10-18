import { useMutation, useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, fileUrl, gbp } from "@/src/api";
import { Button, Card, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { SavedEstimate } from "./ai-estimates";

const mid = (e: SavedEstimate) => (e.total_low + e.total_high) / 2;

/** Two saved AI estimates side by side: design, totals, finish and items, with the cheaper option highlighted. */
export default function CompareEstimates() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { a, b } = useLocalSearchParams<{ a: string; b: string }>();
  const qa = useQuery({ queryKey: ["ai-estimate", a], queryFn: () => api<SavedEstimate>(`/ai/estimates/${a}`) });
  const qb = useQuery({ queryKey: ["ai-estimate", b], queryFn: () => api<SavedEstimate>(`/ai/estimates/${b}`) });
  const toast = useToast();
  const choose = useMutation({
    mutationFn: (eid: string) => api<{ added: number }>(`/ai/estimates/${eid}/choose`, { method: "POST" }),
    onSuccess: (r) => {
      ["ai-estimate", "ai-estimates"].forEach((k) => queryClient.invalidateQueries({ queryKey: [k] }));
      invalidate("line-items", "project");
      toast(`Chosen · ${r.added} item${r.added === 1 ? "" : "s"} added to budget`);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const A = qa.data, B = qb.data;

  if (!A || !B) return <FormScreen title="Compare estimates" testID="compare-screen"><ActivityIndicator color={colors.brand} /></FormScreen>;
  const diff = Math.abs(mid(A) - mid(B));
  const cheaper = mid(A) === mid(B) ? null : mid(A) < mid(B) ? A.id : B.id;
  const cols = [A, B];
  const names = new Set([...A.items, ...B.items].map((i) => i.name.toLowerCase()));

  return (
    <FormScreen title="Compare estimates" testID="compare-screen">
      <Card style={{ gap: 4 }} testID="compare-summary">
        <Text style={s.name}>{cheaper ? `${(cheaper === A.id ? A : B).title || "Option " + (cheaper === A.id ? "A" : "B")} is about ${gbp(diff)} cheaper` : "Both cost about the same"}</Text>
        <Text style={s.muted}>Based on the middle of each price range.</Text>
      </Card>
      <View style={s.cols}>
        {cols.map((e, i) => (
          <Pressable key={e.id} onPress={() => { tap(); router.push({ pathname: "/ai-estimate-view", params: { id: e.id } }); }}
            style={[s.col, cheaper === e.id && { borderColor: colors.success, borderWidth: 2 }]} testID={`compare-col-${i === 0 ? "a" : "b"}`}>
            <Text style={s.tag}>{i === 0 ? "OPTION A" : "OPTION B"}{cheaper === e.id ? " · CHEAPER" : ""}</Text>
            {e.design_path || e.photo_path ? (
              <Image source={{ uri: fileUrl((e.design_path || e.photo_path)!) }} style={s.img} contentFit="cover" />
            ) : <View style={[s.img, s.noImg]}><Icon name="image-off" size={20} color={colors.muted} /></View>}
            <Text style={s.title} numberOfLines={3}>{e.title || e.description}</Text>
            <Text style={s.range} testID={`compare-total-${i === 0 ? "a" : "b"}`}>{gbp(e.total_low)} – {gbp(e.total_high)}</Text>
            <Text style={s.muted}>{e.finish_type} · {e.items.length} items</Text>
            <Text style={s.muted}>{e.created_at.slice(0, 10)}</Text>
            {e.chosen ? <Text style={[s.tag, { color: colors.success }]} testID={`compare-chosen-${i === 0 ? "a" : "b"}`}>✓ CHOSEN</Text> : (
              <Button small title="Choose" icon="trophy" loading={choose.isPending && choose.variables === e.id} onPress={() => choose.mutate(e.id)} testID={`compare-choose-${i === 0 ? "a" : "b"}`} />
            )}
          </Pressable>
        ))}
      </View>
      <Text style={s.section}>Items</Text>
      <Card style={{ gap: space.sm }} testID="compare-items">
        {[...names].map((n) => {
          const [x, y] = cols.map((e) => e.items.find((i) => i.name.toLowerCase() === n));
          return (
            <View key={n} style={{ gap: 2 }}>
              <Text style={s.itemName}>{(x || y)!.name}</Text>
              <View style={s.cols}>
                {[x, y].map((it, i) => (
                  <Text key={i} style={[s.cell, !it && { color: colors.muted }]}>{it ? `${gbp(it.low)} – ${gbp(it.high)}` : "Not included"}</Text>
                ))}
              </View>
            </View>
          );
        })}
      </Card>
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  cols: { flexDirection: "row", gap: space.sm },
  col: { flex: 1, gap: 4, backgroundColor: c.surface, borderRadius: radius.lg, padding: space.sm, borderWidth: 1, borderColor: c.border },
  tag: { fontFamily: fonts.bold, fontSize: 10, letterSpacing: 0.6, color: c.brandPrimary },
  img: { width: "100%", aspectRatio: 1, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  noImg: { alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  range: { fontFamily: fonts.bold, fontSize: 14, color: c.brand },
  section: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  itemName: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  cell: { flex: 1, fontFamily: fonts.medium, fontSize: 12, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
}));
