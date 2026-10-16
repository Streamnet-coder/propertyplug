import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { Modal, Platform, Pressable, ScrollView, Share, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, DocFolder } from "@/src/api";
import { Button, Field, fonts, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export const useFolders = () => useQuery({ queryKey: ["doc-folders"], queryFn: () => api<DocFolder[]>("/doc-folders") });

/** Create a folder link for the selected documents (docIds) or manage existing folder links (docIds empty). */
export function FolderSheet({ docIds, visible, onClose, onCreated, projectName }: { docIds: string[]; visible: boolean; onClose: () => void; onCreated: () => void; projectName?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const folders = useFolders();
  const [title, setTitle] = useState("");
  const [created, setCreated] = useState<DocFolder | null>(null);

  const create = useMutation({
    mutationFn: () => api<DocFolder>("/doc-folders", { body: { title: title.trim() || `${projectName ?? "Project"} documents`, doc_ids: docIds, origin_url: BACKEND_URL } }),
    onSuccess: (f) => { setCreated(f); queryClient.invalidateQueries({ queryKey: ["doc-folders"] }); onCreated(); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/doc-folders/${id}`, { method: "DELETE" }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["doc-folders"] }); toast("Folder link turned off", "info"); },
  });
  const share = async (f: DocFolder) => {
    if (Platform.OS === "web") { await Clipboard.setStringAsync(f.url); toast("Link copied"); return; }
    await Share.share({ message: `${f.title} (${f.doc_count} documents): ${f.url}`, url: f.url });
  };
  const close = () => { setCreated(null); setTitle(""); onClose(); };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={close} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="folder-sheet">
          {docIds.length > 0 && !created ? (
            <>
              <Text style={s.title}>Share {docIds.length} document{docIds.length === 1 ? "" : "s"} as one link</Text>
              <Text style={s.muted}>Lenders and partners open one page and download each file or everything as a ZIP.</Text>
              <Field label="Folder name" value={title} onChangeText={setTitle} placeholder={`${projectName ?? "Project"} documents`} testID="folder-title-input" />
              <Button icon="folder-symlink" title="Create folder link" loading={create.isPending} onPress={() => create.mutate()} testID="folder-create-button" />
            </>
          ) : created ? (
            <>
              <Text style={s.title}>Folder link ready</Text>
              <Text style={s.url} selectable testID="folder-url">{created.url}</Text>
              <View style={{ flexDirection: "row", gap: space.sm }}>
                <Button small icon="share-2" title="Share" onPress={() => share(created)} style={{ flex: 1 }} testID="folder-share-button" />
                <Button small variant="outline" icon="copy" title="Copy" onPress={async () => { await Clipboard.setStringAsync(created.url); toast("Link copied"); }} style={{ flex: 1 }} testID="folder-copy-button" />
              </View>
            </>
          ) : (
            <>
              <Text style={s.title}>Folder links</Text>
              <Text style={s.muted}>Tap “Select” on the Documents screen to bundle files into a new link.</Text>
            </>
          )}
          {(folders.data ?? []).length > 0 && (
            <ScrollView style={{ maxHeight: 240 }} contentContainerStyle={{ gap: space.sm }}>
              <Text style={s.label}>Active folder links</Text>
              {folders.data!.map((f) => (
                <View key={f.id} style={s.row} testID={`folder-row-${f.id}`}>
                  <Icon name="folder" size={18} color={colors.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.name} numberOfLines={1}>{f.title}</Text>
                    <Text style={s.muted}>{f.doc_count} document{f.doc_count === 1 ? "" : "s"}</Text>
                  </View>
                  <Pressable onPress={() => share(f)} style={s.icon} hitSlop={4} testID={`folder-reshare-${f.id}`}><Icon name="share-2" size={16} color={colors.brand} /></Pressable>
                  <Pressable onPress={() => remove.mutate(f.id)} style={s.icon} hitSlop={4} testID={`folder-revoke-${f.id}`}><Icon name="link-2-off" size={16} color={colors.error} /></Pressable>
                </View>
              ))}
            </ScrollView>
          )}
          <Button variant="outline" title="Done" onPress={close} testID="folder-done-button" />
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  label: { fontFamily: fonts.bold, fontSize: 14, color: c.onSurface },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.sm, borderRadius: radius.md, backgroundColor: c.surfaceSecondary },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surface, alignItems: "center", justifyContent: "center" },
}));
