import { useMutation } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Modal, Pressable, RefreshControl, ScrollView, Text, View, useWindowDimensions } from "react-native";
import Animated, { FadeIn } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fileUrl, gbp, MediaItem, Receipt } from "@/src/api";
import { Button, Chip, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { MAX_CONTENT, useLayout } from "@/src/layout";
import { usesNativeTabs } from "@/src/navigation";
import { invalidate, useMedia, useReceipts } from "@/src/queries";
import { useCanSeeMoney } from "@/src/money";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Tab = "photos" | "receipts";
const imgSrc = (m: { url?: string | null; storage_path?: string | null }) => (m.storage_path ? fileUrl(m.storage_path) : m.url ?? undefined);

export default function MediaScreen() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const router = useRouter();
  const params = useLocalSearchParams<{ tab?: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { width } = useWindowDimensions();
  const { wide, tablet } = useLayout();
  const [tab, setTab] = useState<Tab>("photos");
  const [preview, setPreview] = useState<{ kind: Tab; item: MediaItem | Receipt } | null>(null);
  const media = useMedia();
  const money = useCanSeeMoney();
  const receipts = useReceipts(money);

  useEffect(() => {
    if ((params.tab === "receipts" && money) || params.tab === "photos") setTab(params.tab);
  }, [params.tab, money]);

  const del = useMutation({
    mutationFn: (p: { kind: Tab; id: string }) => api(p.kind === "photos" ? `/media/${p.id}` : `/receipts/${p.id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate("media", "receipts", "project");
      setPreview(null);
      toast("Deleted");
    },
  });

  const cols = wide ? 4 : tablet ? 3 : 2;
  const pad = wide ? space.xl : space.lg;
  const avail = wide ? Math.min(width - 240, MAX_CONTENT) : tablet ? width : Math.min(width, 700);
  const cell = Math.floor((avail - pad * 2 - space.md * (cols - 1)) / cols);
  const contained = wide ? { width: "100%" as const, maxWidth: MAX_CONTENT, alignSelf: "center" as const } : null;
  const q = tab === "photos" ? media : receipts;
  const phaseColor = { before: colors.surfaceInverse, progress: colors.accent, after: colors.success };

  return (
    <View style={s.root} testID="media-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.headRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>Media</Text>
            <Text style={s.muted}>Before & after photos and receipts</Text>
          </View>
          <Pressable testID="media-compare-button" onPress={() => { tap(); router.push("/compare"); }} style={({ pressed }) => [s.compareBtn, pressed && { opacity: 0.85 }]}>
            <Icon name="chevrons-left-right" size={16} color={colors.brand} />
            <Text style={s.compareText}>Compare</Text>
          </Pressable>
        </View>
      </View>
      <View style={s.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          <Chip label={`Photos${media.data ? ` (${media.data.length})` : ""}`} icon="image" selected={tab === "photos"} onPress={() => setTab("photos")} testID="media-tab-photos" />
          {money && <Chip label={`Receipts${receipts.data ? ` (${receipts.data.length})` : ""}`} icon="receipt" selected={tab === "receipts"} onPress={() => setTab("receipts")} testID="media-tab-receipts" />}
        </ScrollView>
      </View>

      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.muted}>Failed to load media.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="media-retry-button" />
        </View>
      ) : tab === "photos" ? (
        <FlatList
          key={`photos-${cols}`}
          data={media.data}
          numColumns={cols}
          keyExtractor={(i) => i.id}
          columnWrapperStyle={{ gap: space.md }}
          contentContainerStyle={[{ padding: pad, paddingBottom: bottomChrome + 100, gap: space.md }, contained]}
          refreshControl={<RefreshControl refreshing={media.isRefetching} onRefresh={() => invalidate("media")} tintColor={colors.brand} />}
          renderItem={({ item }) => (
            <Animated.View entering={FadeIn}>
              <Pressable testID={`media-item-${item.id}`} onPress={() => { tap(); setPreview({ kind: "photos", item }); }} style={[s.tile, { width: cell }]}>
                <Image source={{ uri: imgSrc(item) }} style={{ width: cell, height: cell * 0.8, backgroundColor: colors.surfaceTertiary }} contentFit="cover" transition={200} />
                <View style={[s.phase, { backgroundColor: phaseColor[item.phase] }]}>
                  <Text style={s.phaseText}>{item.phase.toUpperCase()}</Text>
                </View>
                <View style={{ padding: space.sm }}>
                  <Text style={s.tileTitle} numberOfLines={1}>{item.title}</Text>
                  <Text style={s.muted}>{item.date}</Text>
                </View>
              </Pressable>
            </Animated.View>
          )}
          ListEmptyComponent={<EmptyState icon="camera" title="No photos yet" subtitle="Capture before & after shots to document progress." testID="media-empty" />}
        />
      ) : (
        <FlatList
          key={wide ? "receipts-grid" : "receipts"}
          data={receipts.data}
          numColumns={wide ? 2 : 1}
          columnWrapperStyle={wide ? { gap: space.md } : undefined}
          keyExtractor={(i) => i.id}
          contentContainerStyle={[{ padding: pad, paddingBottom: bottomChrome + 100, gap: space.sm }, contained]}
          refreshControl={<RefreshControl refreshing={receipts.isRefetching} onRefresh={() => invalidate("receipts")} tintColor={colors.brand} />}
          renderItem={({ item }) => (
            <Pressable testID={`receipt-item-${item.id}`} onPress={() => { tap(); setPreview({ kind: "receipts", item }); }} style={[s.receipt, wide && { flex: 1, maxWidth: "50%" }]}>
              {item.storage_path ? (
                <Image source={{ uri: imgSrc(item) }} style={s.thumb} contentFit="cover" />
              ) : (
                <View style={[s.thumb, { alignItems: "center", justifyContent: "center", backgroundColor: colors.brandTertiary }]}>
                  <Icon name="receipt" size={20} color={colors.brand} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={s.tileTitle} numberOfLines={1}>{item.title}</Text>
                <Text style={s.muted}>{item.supplier || item.category} · {item.date}</Text>
              </View>
              <Text style={s.amt}>{gbp(item.amount, 2)}</Text>
            </Pressable>
          )}
          ListEmptyComponent={<EmptyState icon="receipt" title="No receipts yet" subtitle="Upload your first receipt to keep costs on record." testID="receipts-empty" />}
        />
      )}

      <Pressable
        testID="media-upload-fab"
        onPress={() => { tap(); router.push(tab === "photos" ? "/media-form" : "/receipt-form"); }}
        style={({ pressed }) => [s.fab, { bottom: bottomChrome + space.lg }, pressed && { transform: [{ scale: 0.94 }] }]}
      >
        <Icon name={tab === "photos" ? "camera" : "plus"} size={24} color={colors.onBrandPrimary} />
      </Pressable>

      <Modal visible={!!preview} transparent animationType="fade" onRequestClose={() => setPreview(null)}>
        <Pressable style={s.overlay} onPress={() => setPreview(null)}>
          {preview && (
            <Pressable style={s.sheet} testID="media-preview-modal" onPress={() => {}}>
              {imgSrc(preview.item as any) ? (
                <Image source={{ uri: imgSrc(preview.item as any) }} style={s.big} contentFit="contain" />
              ) : null}
              <Text style={s.sheetTitle}>{preview.item.title}</Text>
              {"amount" in preview.item ? (
                <Text style={s.muted}>{gbp(preview.item.amount, 2)} · {preview.item.supplier} · {preview.item.date}</Text>
              ) : (
                <Text style={s.muted}>{preview.item.phase} · {preview.item.date}</Text>
              )}
              <View style={{ flexDirection: "row", gap: space.sm, marginTop: space.md }}>
                <Button variant="outline" title="Close" onPress={() => setPreview(null)} style={{ flex: 1 }} testID="media-preview-close" />
                <Button variant="danger" icon="trash-2" title="Delete" loading={del.isPending} onPress={() => del.mutate({ kind: preview.kind, id: preview.item.id })} style={{ flex: 1 }} testID="media-preview-delete" />
              </View>
            </Pressable>
          )}
        </Pressable>
      </Modal>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  headRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  compareBtn: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.brandTertiary },
  compareText: { fontFamily: fonts.bold, fontSize: 13, color: c.brand },
  title: { fontFamily: fonts.extrabold, fontSize: 28, color: c.onSurface, letterSpacing: -0.5 },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  chipRow: { height: 56, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, justifyContent: "center" },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  tile: { backgroundColor: c.surface, borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: c.border },
  phase: { position: "absolute", top: space.sm, left: space.sm, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  phaseText: { fontFamily: fonts.bold, fontSize: 9, color: c.onSurfaceInverse, letterSpacing: 0.6 },
  tileTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  receipt: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: space.md,
  },
  thumb: { width: 48, height: 48, borderRadius: radius.sm, backgroundColor: c.surfaceTertiary },
  amt: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  fab: {
    position: "absolute",
    right: space.lg,
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: c.brandPrimary,
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "center", padding: space.lg },
  sheet: { backgroundColor: c.surface, borderRadius: radius.lg, padding: space.lg, gap: space.xs, width: "100%", maxWidth: 640, alignSelf: "center" },
  big: { width: "100%", height: 260, borderRadius: radius.md, backgroundColor: c.surfaceTertiary, marginBottom: space.sm },
  sheetTitle: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
}));
