import { useMutation } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fileUrl, Snag } from "@/src/api";
import { Button, Chip, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { PdfButton } from "@/src/components/pdf-button";
import { SignoffPanel } from "@/src/components/signoff-panel";
import { SnagShareSheet } from "@/src/components/snag-share-sheet";
import { shareSnagPdf } from "@/src/report";
import { invalidate, useSnags } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function Snags() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useSnags();
  const [room, setRoom] = useState("All");
  const [showFixed, setShowFixed] = useState(true);
  const [sharing, setSharing] = useState(false);
  const all = useMemo(() => q.data ?? [], [q.data]);
  const rooms = useMemo(() => ["All", ...Array.from(new Set(all.map((x) => x.room)))], [all]);
  const list = all.filter((x) => (room === "All" || x.room === room) && (showFixed || x.status === "open")).sort((a, b) => (a.status === b.status ? 0 : a.status === "open" ? -1 : 1));
  const open = all.filter((x) => x.status === "open").length;
  const prio = { high: colors.error, medium: colors.brandPrimary, low: colors.muted };

  const toggle = useMutation({
    mutationFn: (x: Snag) => api(`/snags/${x.id}`, { method: "PUT", body: { status: x.status === "open" ? "fixed" : "open" } }),
    onSuccess: (_d, x) => {
      invalidate("snags", "snag-signoffs");
      if (x.status === "open") toast("Snag ticked off");
    },
  });

  return (
    <View style={s.root} testID="snags-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.topRow}>
          <Pressable testID="snags-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
            <Icon name="arrow-left" size={22} />
          </Pressable>
          <Text style={[s.headerTitle, { flex: 1, marginLeft: space.md }]}>Snagging list</Text>
          <PdfButton onGenerate={shareSnagPdf} testID="snags-pdf-button" />
          <Pressable testID="snags-share-button" onPress={() => { tap(); setSharing(true); }} style={s.back} hitSlop={10}>
            <Icon name="send" size={20} color={colors.brand} />
          </Pressable>
          <Pressable testID="snags-toggle-fixed" onPress={() => setShowFixed((v) => !v)} style={s.back} hitSlop={10}>
            <Icon name={showFixed ? "eye" : "eye-off"} size={20} color={colors.muted} />
          </Pressable>
        </View>
        <View style={s.summary} testID="snags-summary">
          <Text style={s.sumBig}>{open} open</Text>
          <Text style={s.muted}>{all.length - open} of {all.length} fixed{open === 0 && all.length ? " · ready for sign-off" : ""}</Text>
        </View>
      </View>
      <View style={s.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {rooms.map((r) => (
            <Chip key={r} label={r} selected={room === r} onPress={() => setRoom(r)} testID={`snag-room-${r.replace(/\s+/g, "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Could not load snags.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="snags-retry-button" />
        </View>
      ) : (
        <FlatList
          data={list}
          keyExtractor={(x) => x.id}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListHeaderComponent={room === "All" ? <SignoffPanel snags={all} /> : null}
          ListEmptyComponent={<EmptyState icon="list-checks" title="No snags logged" subtitle="Walk each room before sign-off and log defects with a photo." testID="snags-empty" />}
          renderItem={({ item, index }) => (
            <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 30)}>
              <Pressable testID={`snag-row-${item.id}`} onPress={() => router.push({ pathname: "/snag-form", params: { id: item.id } })} style={[s.card, item.status === "fixed" && { opacity: 0.6 }]}>
                <Pressable testID={`snag-toggle-${item.id}`} onPress={() => { tap(); toggle.mutate(item); }} hitSlop={10} style={[s.check, item.status === "fixed" && { backgroundColor: colors.success, borderColor: colors.success }]}>
                  {item.status === "fixed" && <Icon name="check" size={14} color={colors.onSuccess} />}
                </Pressable>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[s.desc, item.status === "fixed" && { textDecorationLine: "line-through" }]} numberOfLines={2}>{item.description}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <View style={[s.dot, { backgroundColor: prio[item.priority] }]} />
                    <Text style={s.muted}>{item.room} · {item.priority}{item.assignee ? ` · ${item.assignee}` : ""}</Text>
                  </View>
                  {item.fixed_by ? (
                    <Text style={[s.muted, { color: colors.success, fontFamily: fonts.semibold }]} testID={`snag-fixed-by-${item.id}`}>
                      Fixed by {item.fixed_by}{item.fix_photo_path ? " · photo" : ""}
                    </Text>
                  ) : null}
                </View>
                {item.fix_photo_path || item.storage_path ? <Image source={{ uri: fileUrl((item.fix_photo_path || item.storage_path)!) }} style={s.thumb} contentFit="cover" /> : null}
              </Pressable>
            </Animated.View>
          )}
        />
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        <Button title="Log snag" icon="plus" onPress={() => router.push({ pathname: "/snag-form", params: room !== "All" ? { room } : {} })} testID="add-snag-button" />
      </View>
      <SnagShareSheet visible={sharing} onClose={() => setSharing(false)} snags={all} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, gap: space.md },
  topRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  summary: { flexDirection: "row", alignItems: "baseline", gap: space.md },
  sumBig: { fontFamily: fonts.extrabold, fontSize: 24, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  chipRow: { height: 56, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, justifyContent: "center" },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  check: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  desc: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  dot: { width: 8, height: 8, borderRadius: 4 },
  thumb: { width: 48, height: 48, borderRadius: radius.sm, backgroundColor: c.surfaceTertiary },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
