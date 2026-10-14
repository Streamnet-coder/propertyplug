import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { Linking, Modal, Platform, Pressable, Share, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL, Snag } from "@/src/api";
import { Button, EmptyState, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useContacts, useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export function SnagShareSheet({ visible, onClose, snags }: { visible: boolean; onClose: () => void; snags: Snag[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const team = useContacts("trade");
  const { data: project } = useProject();
  const [busy, setBusy] = useState<string | null>(null);

  const groups = Object.values(
    snags
      .filter((x) => x.assignee.trim())
      .reduce<Record<string, { name: string; open: number; total: number }>>((a, x) => {
        const k = x.assignee.trim().toLowerCase();
        a[k] = a[k] ?? { name: x.assignee.trim(), open: 0, total: 0 };
        a[k].total += 1;
        if (x.status === "open") a[k].open += 1;
        return a;
      }, {}),
  );

  const send = async (name: string, open: number) => {
    setBusy(name);
    try {
      const { url } = await api<{ url: string }>("/snag-links", { body: { assignee: name, origin_url: BACKEND_URL } });
      const msg = `Hi ${name}, here are the ${open} snag${open === 1 ? "" : "s"} for ${project?.name ?? "the project"}. Please mark each one fixed with a photo: ${url}`;
      const phone = team.data?.find((c) => c.name.toLowerCase() === name.toLowerCase())?.phone.replace(/[^\d]/g, "").replace(/^0/, "44");
      if (phone) await Linking.openURL(`https://wa.me/${phone}?text=${encodeURIComponent(msg)}`);
      else if (Platform.OS === "web") {
        await Clipboard.setStringAsync(url);
        toast("Snag link copied");
      } else await Share.share({ message: msg });
    } catch (e: any) {
      toast(e?.message ?? "Couldn't share link", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="snag-share-sheet">
          <Text style={s.title}>Send snags to a trade</Text>
          <Text style={s.muted}>Each trade gets a private link showing only their snags. They can mark them fixed with a photo, no app needed.</Text>
          {groups.length === 0 ? (
            <EmptyState icon="user-plus" title="No snags assigned yet" subtitle="Edit a snag and pick an assigned trade first." testID="snag-share-empty" />
          ) : (
            groups.map((g) => (
              <View key={g.name} style={s.row} testID={`snag-share-row-${g.name.replace(/\s+/g, "-").toLowerCase()}`}>
                <View style={s.avatar}><Icon name="hard-hat" size={18} color={colors.brand} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={s.name}>{g.name}</Text>
                  <Text style={s.muted}>{g.open} open · {g.total - g.open} fixed</Text>
                </View>
                <Button
                  small
                  icon="send"
                  title="Send link"
                  loading={busy === g.name}
                  onPress={() => { tap(); send(g.name, g.open); }}
                  testID={`snag-share-send-${g.name.replace(/\s+/g, "-").toLowerCase()}`}
                />
              </View>
            ))
          )}
          <Button variant="outline" title="Close" onPress={onClose} testID="snag-share-close" />
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.sm, borderTopWidth: 1, borderTopColor: c.divider },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
}));
