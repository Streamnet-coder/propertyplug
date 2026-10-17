import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fileUrl, MediaItem } from "@/src/api";
import { BeforeAfterSlider } from "@/src/components/before-after-slider";
import { ShareCompare } from "@/src/components/share-compare";
import { Button, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useMedia, useMilestones } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

const src = (m?: MediaItem) => (m ? (m.storage_path ? fileUrl(m.storage_path) : m.url ?? undefined) : undefined);

export default function Compare() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const params = useLocalSearchParams<{ milestone_id?: string; before?: string; after?: string }>();
  const media = useMedia();
  const milestones = useMilestones();
  const stage = milestones.data?.find((m) => m.id === params.milestone_id);

  const photos = useMemo(() => (media.data ?? []).filter((m) => !params.milestone_id || m.milestone_id === params.milestone_id), [media.data, params.milestone_id]);
  const befores = photos.filter((m) => m.phase === "before");
  const afters = photos.filter((m) => m.phase !== "before");
  const [b, setB] = useState<string>();
  const [a, setA] = useState<string>();

  useEffect(() => {
    if (!b && befores.length) setB(params.before && befores.some((m) => m.id === params.before) ? params.before : befores[0].id);
    if (!a && afters.length) setA(params.after && afters.some((m) => m.id === params.after) ? params.after : (afters.find((m) => m.phase === "after") ?? afters[0]).id);
  }, [befores, afters, a, b, params.before, params.after]);

  const before = befores.find((m) => m.id === b);
  const after = afters.find((m) => m.id === a);
  const h = Math.min(width - space.lg * 2, 700) * 0.78;

  const strip = (label: string, list: MediaItem[], sel: string | undefined, pick: (id: string) => void, kind: string) => (
    <View style={{ gap: space.sm }}>
      <Text style={s.label}>{label} ({list.length})</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        {list.map((m) => (
          <Pressable key={m.id} testID={`compare-${kind}-${m.id}`} onPress={() => { tap(); pick(m.id); }} style={[s.thumbWrap, sel === m.id && { borderColor: colors.brand }]}>
            <Image source={{ uri: src(m) }} style={s.thumb} contentFit="cover" />
            {sel === m.id && <View style={s.check}><Icon name="check" size={12} color={colors.onBrand} /></View>}
            <Text style={s.thumbTitle} numberOfLines={1}>{m.title}</Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );

  return (
    <View style={s.root} testID="compare-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <Pressable testID="compare-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={s.headerTitle}>Before & after</Text>
          {stage && <Text style={s.muted} numberOfLines={1}>{stage.name}</Text>}
        </View>
        <View style={{ width: 44 }} />
      </View>
      {media.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : !befores.length || !afters.length ? (
        <View style={{ padding: space.lg, gap: space.lg }}>
          <EmptyState icon="images" title="Need a before and an after" subtitle={`Add at least one before photo and one progress or after photo${stage ? " for this stage" : ""} to compare them side by side.`} testID="compare-empty" />
          <Button title="Add photo" icon="camera" onPress={() => router.push({ pathname: "/media-form", params: params.milestone_id ? { milestone_id: params.milestone_id, phase: befores.length ? "after" : "before", stage: stage?.name ?? "" } : {} })} testID="compare-add-photo" />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.xl, paddingBottom: insets.bottom + space.xxl }}>
          <View style={{ gap: space.sm }}>
            <BeforeAfterSlider before={src(before)} after={src(after)} height={h} />
            <Text style={[s.muted, { textAlign: "center" }]}>Drag the handle to reveal the transformation</Text>
          </View>
          {strip("Before photo", befores, b, setB, "before")}
          {strip("After / progress photo", afters, a, setA, "after")}
          <ShareCompare beforeId={b} afterId={a} title={stage?.name ?? ""} />
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  thumbWrap: { width: 104, borderRadius: radius.md, borderWidth: 2, borderColor: "transparent", backgroundColor: c.surface, overflow: "hidden" },
  thumb: { width: "100%", height: 76, backgroundColor: c.surfaceTertiary },
  thumbTitle: { fontFamily: fonts.medium, fontSize: 11, color: c.onSurface, padding: 6 },
  check: { position: "absolute", top: 6, right: 6, width: 20, height: 20, borderRadius: 10, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
}));
