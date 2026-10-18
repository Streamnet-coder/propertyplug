import { useMutation } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { api, fileUrl, Project } from "@/src/api";
import { PhotoPicker } from "@/src/components/photo-picker";
import { Button, Card, fonts, radius, SectionTitle, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadAsset } from "@/src/upload";

const fmt = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

/** Before & now strip on home: every photo set as the project photo, oldest to newest. Add a progress photo to update the banner. */
export function PhotoTimelineCard({ p }: { p: Project }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const hist = p.cover_history?.length ? p.cover_history : p.cover_path ? [{ path: p.cover_path, at: "" }] : [];
  const remove = useMutation({
    mutationFn: (path: string) => api(`/project/cover-history?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
    onSuccess: () => { invalidate("project", "projects"); toast("Photo removed from timeline"); },
  });
  if (!hist.length) return null;
  const first = hist[0];
  const now = hist[hist.length - 1];

  return (
    <View testID="photo-timeline-card">
      <SectionTitle title={hist.length > 1 ? "Before & now" : "Project photo"} action={adding ? undefined : "Add progress photo"} onAction={() => setAdding(true)} testID="photo-timeline-add" />
      <Card style={{ gap: space.md }}>
        {hist.length > 1 ? (
          <View style={s.pair}>
            {[{ e: first, l: "BEFORE" }, { e: now, l: "NOW" }].map(({ e, l }) => (
              <View key={l} style={{ flex: 1, gap: 4 }} testID={`photo-timeline-${l.toLowerCase()}`}>
                <Image source={{ uri: fileUrl(e.path) }} style={s.big} contentFit="cover" />
                <Text style={s.tag}>{l}</Text>
                <Text style={s.muted}>{fmt(e.at)}</Text>
              </View>
            ))}
          </View>
        ) : (
          <Text style={s.muted}>Add a progress photo as works go on to build a before &amp; now timeline. The newest photo becomes your banner.</Text>
        )}
        {hist.length > 2 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }} testID="photo-timeline-strip">
            {hist.map((e, i) => (
              <Pressable key={e.path + i} onLongPress={() => remove.mutate(e.path)} testID={`photo-timeline-item-${i}`}>
                <Image source={{ uri: fileUrl(e.path) }} style={[s.thumb, e.path === p.cover_path && { borderColor: colors.brand, borderWidth: 2 }]} contentFit="cover" />
                <Text style={s.muted}>{fmt(e.at) || "—"}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}
        {hist.length > 2 && <Text style={s.muted}>Long-press a photo to remove it from the timeline.</Text>}
        {adding && (
          <View style={{ gap: space.sm }} testID="photo-timeline-picker">
            <PhotoPicker value={null} hint="Take or pick a photo of how it looks today."
              onChange={async (a) => {
                if (!a) return;
                tap();
                setBusy(true);
                try {
                  await api("/project/cover", { method: "PUT", body: { storage_path: await uploadAsset(a) } });
                  invalidate("project", "projects");
                  toast("Progress photo added");
                  setAdding(false);
                } catch (e) {
                  toast((e as Error).message, "error");
                } finally {
                  setBusy(false);
                }
              }} />
            <Button small variant="outline" title={busy ? "Uploading…" : "Cancel"} disabled={busy} onPress={() => setAdding(false)} testID="photo-timeline-cancel" />
          </View>
        )}
      </Card>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  pair: { flexDirection: "row", gap: space.sm },
  big: { width: "100%", aspectRatio: 1, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  thumb: { width: 72, height: 72, borderRadius: radius.sm, backgroundColor: c.surfaceTertiary },
  tag: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 0.6, color: c.brandPrimary },
  muted: { fontFamily: fonts.regular, fontSize: 11, color: c.muted, lineHeight: 16 },
}));
