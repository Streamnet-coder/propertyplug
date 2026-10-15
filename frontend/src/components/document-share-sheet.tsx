import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { Linking, Modal, Platform, Pressable, ScrollView, Share, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, DocItem, logMessage, Stakeholder } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

/** Share one document with a stakeholder (WhatsApp / email, logged) or anyone via the system share sheet. */
export function DocumentShareSheet({ doc, onClose }: { doc: DocItem | null; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const people = useQuery({ queryKey: ["stakeholders"], queryFn: () => api<Stakeholder[]>("/stakeholders"), enabled: !!doc });
  const create = useMutation({
    mutationFn: () => api<DocItem>(`/documents/${doc!.id}/share`, { body: { origin_url: BACKEND_URL } }),
    onSuccess: () => invalidate("documents"),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const revoke = useMutation({
    mutationFn: () => api<DocItem>(`/documents/${doc!.id}/share`, { method: "DELETE" }),
    onSuccess: () => { invalidate("documents"); toast("Link turned off", "info"); onClose(); },
  });

  const url = create.data?.share_url ?? doc?.share_url ?? null;
  const ensure = async () => url ?? (await create.mutateAsync()).share_url!;
  const msg = (u: string) => `${doc!.doc_type}: ${doc!.title}\n${u}`;

  const toPerson = async (p: Stakeholder, channel: "whatsapp" | "email") => {
    tap();
    const u = await ensure();
    const wa = p.phone.replace(/[^\d]/g, "").replace(/^0/, "44");
    const link = channel === "whatsapp" ? `https://wa.me/${wa}?text=${encodeURIComponent(msg(u))}` : `mailto:${p.email}?subject=${encodeURIComponent(doc!.title)}&body=${encodeURIComponent(msg(u))}`;
    logMessage({ name: p.name, email: p.email, phone: p.phone, channel, kind: "document", summary: `Shared document: ${doc!.title} (${doc!.doc_type})`, url: u });
    Linking.openURL(link).catch(() => toast("Can't open this on your device", "error"));
  };
  const shareAny = async () => {
    tap();
    const u = await ensure();
    if (Platform.OS === "web") { await Clipboard.setStringAsync(u); toast("Link copied"); return; }
    await Share.share({ message: msg(u), url: u });
  };
  const copy = async () => { const u = await ensure(); await Clipboard.setStringAsync(u); toast("Link copied"); };

  return (
    <Modal visible={!!doc} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="document-share-sheet">
          <Text style={s.title} numberOfLines={1}>Share “{doc?.title}”</Text>
          <Text style={s.muted}>Stakeholders get a secure download link. Turn it off any time.</Text>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small icon="share-2" title="Share" onPress={shareAny} loading={create.isPending} style={{ flex: 1 }} testID="document-share-any" />
            <Button small variant="outline" icon="copy" title="Copy link" onPress={copy} style={{ flex: 1 }} testID="document-copy-link" />
          </View>
          {url ? <Text style={s.url} selectable numberOfLines={1} testID="document-share-url">{url}</Text> : null}
          <Text style={s.label}>Send to a stakeholder</Text>
          <ScrollView style={{ maxHeight: 260 }} contentContainerStyle={{ gap: space.sm }}>
            {(people.data ?? []).map((p) => (
              <View key={p.key} style={s.row} testID={`document-share-person-${p.key}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.name} numberOfLines={1}>{p.name}</Text>
                  <Text style={s.muted} numberOfLines={1}>{p.role}</Text>
                </View>
                {p.phone ? (
                  <Pressable onPress={() => toPerson(p, "whatsapp")} style={[s.icon, { backgroundColor: colors.surfaceTertiary }]} hitSlop={4} testID={`document-share-whatsapp-${p.key}`}>
                    <Icon name="message-circle" size={18} color={colors.success} />
                  </Pressable>
                ) : null}
                {p.email ? (
                  <Pressable onPress={() => toPerson(p, "email")} style={[s.icon, { backgroundColor: colors.brandTertiary }]} hitSlop={4} testID={`document-share-email-${p.key}`}>
                    <Icon name="mail" size={18} color={colors.brand} />
                  </Pressable>
                ) : null}
              </View>
            ))}
            {people.data && !people.data.length && <Text style={s.muted}>Add people in the Team tab to send documents directly.</Text>}
          </ScrollView>
          {url ? <Button small variant="danger" icon="link-2-off" title="Turn off link" loading={revoke.isPending} onPress={() => revoke.mutate()} testID="document-revoke-link" /> : null}
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
  url: { fontFamily: fonts.medium, fontSize: 12, color: c.brand },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.sm, borderRadius: radius.md, backgroundColor: c.surfaceSecondary },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  icon: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
}));
