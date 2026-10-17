import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { Linking, Modal, Platform, Pressable, Share, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BACKEND_URL } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useProject } from "@/src/queries";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Link = { url: string | null; reports: number; sms_enabled: boolean; alert_phone: string };

/** One shareable "Report a problem" link per property: tenants report issues without a tenancy or app. */
export function ReportLinkSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { data: project } = useProject();
  const q = useQuery({ queryKey: ["report-link"], queryFn: () => api<Link>("/report-link"), enabled: visible });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["report-link"] });

  const create = useMutation({ mutationFn: () => api<{ url: string }>("/report-link", { body: { origin_url: BACKEND_URL } }), onSuccess: refresh });
  const revoke = useMutation({
    mutationFn: () => api("/report-link", { method: "DELETE" }),
    onSuccess: () => { refresh(); toast("Report link turned off"); },
  });

  const url = q.data?.url;
  const msg = (u: string) => `Hi, if anything needs fixing at ${project?.address || project?.name || "the property"}, report it here with a photo: ${u}`;

  const share = async (via: "whatsapp" | "share" | "copy") => {
    tap();
    const u = url ?? (await create.mutateAsync()).url;
    if (via === "whatsapp") await Linking.openURL(`https://wa.me/?text=${encodeURIComponent(msg(u))}`);
    else if (via === "copy" || Platform.OS === "web") {
      await Clipboard.setStringAsync(u);
      toast("Report link copied");
    } else await Share.share({ message: msg(u) });
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: insets.bottom + space.lg }]} testID="report-link-sheet">
          <View style={s.head}>
            <View style={s.badge}><Icon name="megaphone" size={20} color={colors.brandPrimary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={s.title}>Tenant report link</Text>
              <Text style={s.muted}>Share one link for this property. Tenants add their name, contact, the problem and a photo. No app or tenancy needed.</Text>
            </View>
          </View>
          {url ? (
            <View style={s.urlBox} testID="report-link-url">
              <Icon name="link" size={16} color={colors.brand} />
              <Text style={s.url} numberOfLines={1}>{url}</Text>
            </View>
          ) : (
            <Text style={s.muted} testID="report-link-none">No link yet. Sharing creates one.</Text>
          )}
          {q.data ? <Text style={s.muted} testID="report-link-count">{q.data.reports} problem{q.data.reports === 1 ? "" : "s"} reported through this link</Text> : null}
          {q.data ? (
            <View style={s.alertBox} testID="report-link-urgent-info">
              <Icon name="siren" size={16} color={colors.error} />
              <Text style={[s.muted, { flex: 1 }]}>
                Urgent reports are emailed to you straight away.{" "}
                {q.data.sms_enabled
                  ? q.data.alert_phone ? `They're also texted to ${q.data.alert_phone}.` : "Add your phone in Branding to get them by text too."
                  : "Text alerts switch on once SMS is set up."}
              </Text>
            </View>
          ) : null}
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button icon="message-circle" title="WhatsApp" loading={create.isPending} onPress={() => share("whatsapp")} testID="report-link-whatsapp" /></View>
            <View style={{ flex: 1 }}><Button variant="outline" icon="copy" title="Copy" onPress={() => share("copy")} testID="report-link-copy" /></View>
          </View>
          {Platform.OS !== "web" && <Button variant="outline" icon="share-2" title="Share another way" onPress={() => share("share")} testID="report-link-share" />}
          {url ? (
            <Pressable onPress={() => { tap(); revoke.mutate(); }} style={s.revoke} testID="report-link-revoke" hitSlop={8}>
              <Text style={[s.muted, { color: colors.error, fontFamily: fonts.semibold }]}>Turn off this link</Text>
            </Pressable>
          ) : null}
          <Button variant="outline" title="Close" onPress={onClose} testID="report-link-close" />
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, gap: space.md },
  head: { flexDirection: "row", gap: space.md, alignItems: "flex-start" },
  badge: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.orangeTint, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  urlBox: { flexDirection: "row", alignItems: "center", gap: space.sm, padding: space.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  url: { flex: 1, fontFamily: fonts.medium, fontSize: 13, color: c.onSurface },
  row: { flexDirection: "row", gap: space.sm },
  alertBox: { flexDirection: "row", gap: space.sm, alignItems: "flex-start", padding: space.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  revoke: { alignSelf: "center", paddingVertical: space.xs, minHeight: 44, justifyContent: "center" },
}));
