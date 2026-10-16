import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, Alert, FlatList, Platform, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, DocItem, DOC_TYPES, expiryLabel, fileSize } from "@/src/api";
import { DocumentShareSheet } from "@/src/components/document-share-sheet";
import { FolderSheet } from "@/src/components/folder-sheet";
import { Button, Chip, EmptyState, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { downloadFile } from "@/src/export";
import { invalidate, useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const EXT_ICON: Record<string, IconName> = { pdf: "file-text", doc: "file-type", docx: "file-type", xls: "file-spreadsheet", xlsx: "file-spreadsheet", csv: "file-spreadsheet", txt: "file", jpg: "file-image", jpeg: "file-image", png: "file-image", heic: "file-image", webp: "file-image" };

const confirm = (msg: string) =>
  Platform.OS === "web" ? Promise.resolve(globalThis.confirm(msg)) : new Promise<boolean>((r) => Alert.alert("Delete document?", msg, [{ text: "Cancel", style: "cancel", onPress: () => r(false) }, { text: "Delete", style: "destructive", onPress: () => r(true) }]));

export default function Documents() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const project = useProject();
  const [type, setType] = useState<string>("All");
  const [query, setQuery] = useState("");
  const [sharing, setSharing] = useState<DocItem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [folderOpen, setFolderOpen] = useState(false);
  const togglePick = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const q = useQuery({ queryKey: ["documents"], queryFn: () => api<DocItem[]>("/documents") });
  const all = useMemo(() => q.data ?? [], [q.data]);
  const counts = useMemo(() => all.reduce<Record<string, number>>((a, d) => ({ ...a, [d.doc_type]: (a[d.doc_type] ?? 0) + 1 }), {}), [all]);
  const list = all.filter((d) => (type === "All" || d.doc_type === type) && (!query.trim() || `${d.title} ${d.filename} ${d.notes}`.toLowerCase().includes(query.trim().toLowerCase())));

  const remove = useMutation({
    mutationFn: (id: string) => api(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => { invalidate("documents"); toast("Document deleted"); },
  });
  const run = async (key: string, fn: () => Promise<void>) => {
    tap();
    setBusy(key);
    try { await fn(); } catch (e: any) { toast(e?.message ?? "Download failed", "error"); } finally { setBusy(null); }
  };
  const zipName = `${(project.data?.name ?? "project").replace(/[^\w]+/g, "-")}-documents.zip`;

  return (
    <View style={s.root} testID="documents-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.topRow}>
          <Pressable testID="documents-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
            <Icon name="arrow-left" size={22} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle}>Documents</Text>
            <Text style={s.muted} numberOfLines={1}>{project.data?.name} · {all.length} file{all.length === 1 ? "" : "s"}</Text>
          </View>
          <Pressable testID="documents-portal-button" onPress={() => { tap(); router.push("/portal-access"); }} style={[s.iconBtn, { backgroundColor: colors.brandTertiary }]} hitSlop={6} accessibilityLabel="Stakeholder portal">
            <Icon name="users" size={20} color={colors.brand} />
          </Pressable>
          <Pressable testID="documents-folders-button" onPress={() => { tap(); setPicked([]); setFolderOpen(true); }} style={[s.iconBtn, { backgroundColor: colors.brandTertiary }]} hitSlop={6} accessibilityLabel="Folder links">
            <Icon name="folder-symlink" size={20} color={colors.brand} />
          </Pressable>
          {all.length > 0 && (
            <Pressable
              testID="documents-download-all"
              onPress={() => run("zip", () => downloadFile(`/documents/zip${type !== "All" ? `?doc_type=${encodeURIComponent(type)}` : ""}`, zipName, "application/zip", "Save documents"))}
              style={[s.iconBtn, { backgroundColor: colors.brandTertiary }]}
              hitSlop={6}
              accessibilityLabel="Download all as ZIP"
            >
              {busy === "zip" ? <ActivityIndicator size="small" color={colors.brand} /> : <Icon name="folder-down" size={20} color={colors.brand} />}
            </Pressable>
          )}
        </View>
        <View style={s.search}>
          <Icon name="search" size={16} color={colors.muted} />
          <TextInput value={query} onChangeText={setQuery} placeholder="Search documents" placeholderTextColor={colors.muted} style={s.input} testID="documents-search-input" />
          {all.length > 0 && (
            <Pressable onPress={() => { tap(); setSelecting(!selecting); setPicked([]); }} hitSlop={8} style={{ minHeight: 44, justifyContent: "center" }} testID="documents-select-toggle">
              <Text style={s.selectText}>{selecting ? "Cancel" : "Select"}</Text>
            </Pressable>
          )}
        </View>
      </View>
      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {["All", ...DOC_TYPES.filter((t) => counts[t])].map((t) => (
            <Chip key={t} label={t === "All" ? `All (${all.length})` : `${t} (${counts[t]})`} selected={type === t} onPress={() => setType(t)} testID={`documents-filter-${t.replace(/\W+/g, "-").toLowerCase()}`} />
          ))}
        </ScrollView>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : (
        <FlatList
          data={list}
          keyExtractor={(d) => d.id}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + 100 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListEmptyComponent={<EmptyState icon="folder-open" title={all.length ? "No matching documents" : "No documents yet"} subtitle="Upload deeds, surveys, certificates, invoices and more, then share them with your team, lender or partners." testID="documents-empty" />}
          renderItem={({ item }) => (
            <Pressable disabled={!selecting} onPress={() => togglePick(item.id)} style={[s.card, picked.includes(item.id) && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]} testID={`document-row-${item.id}`}>
              {selecting && (
                <View style={[s.box, picked.includes(item.id) && { backgroundColor: colors.brand, borderColor: colors.brand }]} testID={`document-pick-${item.id}`}>
                  {picked.includes(item.id) && <Icon name="check" size={14} color={colors.onBrand} />}
                </View>
              )}
              <View style={s.fileIcon}><Icon name={EXT_ICON[item.ext] ?? "file"} size={22} color={colors.brand} /></View>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.name} numberOfLines={2}>{item.title}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: space.xs, flexWrap: "wrap" }}>
                  <View style={s.typePill}><Text style={s.typeText}>{item.doc_type}</Text></View>
                  <Text style={s.muted}>{item.ext.toUpperCase()} · {fileSize(item.size)} · {new Date(item.created_at).toLocaleDateString("en-GB")}</Text>
                  {item.share_url ? <Icon name="link" size={12} color={colors.success} /> : null}
                </View>
                {item.notes ? <Text style={s.muted} numberOfLines={2}>{item.notes}</Text> : null}
                {expiryLabel(item) ? (
                  <View style={[s.expiry, { backgroundColor: item.expiry_status === "expired" ? colors.errorTint : colors.orangeTint }]} testID={`document-expiry-${item.id}`}>
                    <Icon name="calendar-clock" size={12} color={item.expiry_status === "expired" ? colors.error : colors.brandPrimary} />
                    <Text style={[s.expiryText, { color: item.expiry_status === "expired" ? colors.error : colors.brandPrimary }]}>{expiryLabel(item)}</Text>
                  </View>
                ) : item.expires_on ? <Text style={s.muted}>Valid until {new Date(item.expires_on).toLocaleDateString("en-GB")}</Text> : null}
              </View>
              {!selecting && <View style={{ gap: space.xs }}>
                <Pressable onPress={() => run(item.id, () => downloadFile(`/documents/${item.id}/download`, item.filename, item.content_type, item.title))} style={s.act} hitSlop={4} testID={`document-download-${item.id}`} accessibilityLabel="Download">
                  {busy === item.id ? <ActivityIndicator size="small" color={colors.brand} /> : <Icon name="download" size={18} color={colors.brand} />}
                </Pressable>
                <Pressable onPress={() => { tap(); setSharing(item); }} style={s.act} hitSlop={4} testID={`document-share-${item.id}`} accessibilityLabel="Share">
                  <Icon name="share-2" size={18} color={colors.brand} />
                </Pressable>
                <Pressable onPress={async () => { if (await confirm(`Delete “${item.title}”?`)) remove.mutate(item.id); }} style={s.act} hitSlop={4} testID={`document-delete-${item.id}`} accessibilityLabel="Delete">
                  <Icon name="trash-2" size={16} color={colors.error} />
                </Pressable>
              </View>}
            </Pressable>
          )}
        />
      )}
      <View style={[s.cta, { bottom: insets.bottom + space.lg }]}>
        {selecting ? (
          <Button title={picked.length ? `Share ${picked.length} as a folder link` : "Tap documents to select"} icon="folder-symlink" disabled={!picked.length} onPress={() => setFolderOpen(true)} testID="documents-share-folder-button" />
        ) : (
          <Button title="Upload document" icon="upload" onPress={() => router.push("/document-form")} testID="documents-upload-button" />
        )}
      </View>
      <DocumentShareSheet doc={sharing} onClose={() => setSharing(null)} />
      <FolderSheet docIds={picked} visible={folderOpen} projectName={project.data?.name} onClose={() => setFolderOpen(false)} onCreated={() => { setSelecting(false); setPicked([]); }} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, gap: space.md },
  topRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  search: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.md, minHeight: 44, borderRadius: radius.md, backgroundColor: c.surfaceSecondary },
  input: { flex: 1, fontFamily: fonts.regular, fontSize: 14, color: c.onSurface, minHeight: 44 },
  chips: { paddingHorizontal: space.lg, paddingVertical: space.sm, gap: space.sm, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  card: { flexDirection: "row", gap: space.md, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  fileIcon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  typePill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: c.orangeTint },
  typeText: { fontFamily: fonts.semibold, fontSize: 11, color: c.brandPrimary },
  box: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center", alignSelf: "center" },
  selectText: { fontFamily: fonts.semibold, fontSize: 14, color: c.brand },
  expiry: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill, marginTop: 2 },
  expiryText: { fontFamily: fonts.semibold, fontSize: 11 },
  act: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  cta: { position: "absolute", left: space.lg, right: space.lg },
}));
