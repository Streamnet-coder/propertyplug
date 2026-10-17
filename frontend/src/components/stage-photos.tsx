import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { ScrollView, Text, View } from "react-native";

import { fileUrl } from "@/src/api";
import { Button, fonts, radius, space } from "@/src/components/ui";
import { useMedia } from "@/src/queries";
import { makeStyles } from "@/src/theme";

export function StagePhotos({ milestoneId, stage }: { milestoneId: string; stage: string }) {
  const s = useStyles();
  const router = useRouter();
  const media = useMedia();
  const photos = (media.data ?? []).filter((m) => m.milestone_id === milestoneId);
  const add = (phase: "before" | "after") => router.push({ pathname: "/media-form", params: { milestone_id: milestoneId, phase, stage } });

  return (
    <View style={{ gap: space.sm }} testID="stage-photos-section">
      <Text style={s.label}>Stage photos ({photos.length})</Text>
      <Text style={s.muted}>Before & after shots show lenders proof of progress on the live report.</Text>
      {photos.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {photos.map((p) => (
            <View key={p.id} testID={`stage-photo-${p.id}`}>
              <Image source={{ uri: p.storage_path ? fileUrl(p.storage_path) : p.url ?? undefined }} style={s.thumb} contentFit="cover" />
              <View style={[s.tag, p.phase === "after" && s.tagAfter]}>
                <Text style={s.tagText}>{p.phase.toUpperCase()}</Text>
              </View>
            </View>
          ))}
        </ScrollView>
      )}
      {photos.some((p) => p.phase === "before") && photos.some((p) => p.phase !== "before") && (
        <Button small variant="ghost" icon="chevrons-left-right" title="Compare before & after" onPress={() => router.push({ pathname: "/compare", params: { milestone_id: milestoneId } })} testID="stage-compare-button" />
      )}
      <View style={{ flexDirection: "row", gap: space.sm }}>
        <Button small variant="outline" icon="camera" title="Add before" onPress={() => add("before")} style={{ flex: 1 }} testID="stage-add-before-button" />
        <Button small variant="secondary" icon="camera" title="Add after" onPress={() => add("after")} style={{ flex: 1 }} testID="stage-add-after-button" />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  thumb: { width: 110, height: 82, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  tag: { position: "absolute", top: 6, left: 6, backgroundColor: c.surfaceInverse, paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill },
  tagAfter: { backgroundColor: c.success },
  tagText: { fontFamily: fonts.bold, fontSize: 9, color: c.onSurfaceInverse },
}));
