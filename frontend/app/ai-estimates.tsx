import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, fileUrl, gbp } from "@/src/api";
import { DesignPin } from "@/src/components/design-hotspots";
import { Button, Card, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export type SavedEstimate = {
  id: string; title: string; description: string; finish_type: string; created_at: string; photo_path: string | null; design_path: string | null; pins: DesignPin[];
  total_low: number; total_high: number; items: { name: string; spec?: string; category: string; low: number; high: number; supplier: string }[]; notes: string;
};

/** Every AI cost estimate for this project, with its designed finished look, to review later. */
export default function SavedEstimates() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useQuery({ queryKey: ["ai-estimates"], queryFn: () => api<SavedEstimate[]>("/ai/estimates") });

  return (
    <FormScreen title="Saved estimates" testID="saved-estimates-screen">
      {q.isLoading ? <ActivityIndicator color={colors.brand} /> : !q.data?.length ? (
        <Card style={{ gap: space.sm, alignItems: "center" }} testID="saved-estimates-empty">
          <Icon name="sparkles" size={22} color={colors.brand} />
          <Text style={s.muted}>No estimates yet. Every AI estimate and its design image is saved here automatically.</Text>
          <Button small icon="sparkles" title="New AI estimate" onPress={() => router.push("/ai-estimate")} testID="saved-estimates-new" />
        </Card>
      ) : q.data.map((e) => (
        <Pressable key={e.id} onPress={() => { tap(); router.push({ pathname: "/ai-estimate-view", params: { id: e.id } }); }}
          style={({ pressed }) => [s.card, pressed && { opacity: 0.85 }]} testID={`saved-estimate-${e.id}`}>
          {e.design_path || e.photo_path ? (
            <Image source={{ uri: fileUrl((e.design_path || e.photo_path)!) }} style={s.thumb} contentFit="cover" />
          ) : (
            <View style={[s.thumb, s.noImg]}><Icon name="image-off" size={20} color={colors.muted} /></View>
          )}
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={s.name} numberOfLines={2}>{e.title || e.description}</Text>
            <Text style={s.range}>{gbp(e.total_low)} – {gbp(e.total_high)}</Text>
            <Text style={s.muted}>{e.finish_type} · {e.items.length} items · {e.created_at.slice(0, 10)}{e.design_path ? " · design" : ""}</Text>
          </View>
          <Icon name="chevron-right" size={18} color={colors.muted} />
        </Pressable>
      ))}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.lg, padding: space.md, borderWidth: 1, borderColor: c.border },
  thumb: { width: 72, height: 72, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  noImg: { alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  range: { fontFamily: fonts.bold, fontSize: 14, color: c.brand },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
}));
