import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Linking, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Message } from "@/src/api";
import { EmptyState, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const CH: Record<string, IconName> = { email: "mail", whatsapp: "message-circle", call: "phone", link: "link", share: "share-2", web: "globe" };
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function StakeholderLog() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { name = "", email = "", phone = "", role = "" } = useLocalSearchParams<{ name: string; email: string; phone: string; role: string }>();
  const q = useQuery({ queryKey: ["messages", name, email], queryFn: () => api<Message[]>(`/messages?name=${encodeURIComponent(name)}&email=${encodeURIComponent(email)}`) });
  const log = useMutation({
    mutationFn: (b: { channel: string; summary: string }) => api("/messages", { body: { name, email, phone, kind: "message", ...b } }),
    onSuccess: () => q.refetch(),
  });

  const wa = phone.replace(/[^\d]/g, "").replace(/^0/, "44");
  const act = async (channel: string, url: string, summary: string) => {
    tap();
    try {
      await Linking.openURL(url);
      log.mutate({ channel, summary });
    } catch {
      toast("Can't open this on your device", "error");
    }
  };

  return (
    <View style={s.root} testID="stakeholder-log-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.topRow}>
          <Pressable testID="stakeholder-back-button" onPress={() => router.back()} style={s.iconBtn} hitSlop={10}>
            <Icon name="arrow-left" size={22} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle} numberOfLines={1}>{name}</Text>
            <Text style={s.muted} numberOfLines={1}>{[role, email].filter(Boolean).join(" · ")}</Text>
          </View>
        </View>
        <View style={s.actions}>
          {phone ? <Act icon="phone" label="Call" color={colors.brand} onPress={() => act("call", `tel:${phone}`, "Phoned")} testID="stakeholder-call" /> : null}
          {wa ? <Act icon="message-circle" label="WhatsApp" color={colors.success} onPress={() => act("whatsapp", `https://wa.me/${wa}`, "Opened WhatsApp chat")} testID="stakeholder-whatsapp" /> : null}
          {email ? <Act icon="mail" label="Email" color={colors.accent} onPress={() => act("email", `mailto:${email}`, "Emailed from the app")} testID="stakeholder-email" /> : null}
        </View>
      </View>
      {q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : (
        <FlatList
          data={q.data ?? []}
          keyExtractor={(m) => m.id}
          contentContainerStyle={{ padding: space.lg, gap: space.sm, paddingBottom: insets.bottom + space.xl }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brand} />}
          ListHeaderComponent={<Text style={s.note}>Every link, email, WhatsApp, call and reply with {name} is logged here with the time. Replies to emails go to your own inbox.</Text>}
          ListEmptyComponent={<EmptyState icon="messages-square" title="No messages yet" subtitle="Send a snag link, quote request or weekly update and it will appear here." testID="stakeholder-log-empty" />}
          renderItem={({ item }) => {
            const inbound = item.direction === "in";
            return (
              <View style={[s.msg, inbound ? s.in : s.out]} testID={`message-${item.id}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Icon name={CH[item.channel] ?? "message-square"} size={14} color={inbound ? colors.brandPrimary : colors.brand} />
                  <Text style={s.meta}>{inbound ? `From ${name}` : "You"} · {item.channel} · {when(item.created_at)}</Text>
                  {item.status === "failed" && <Text style={[s.meta, { color: colors.error }]}>· failed</Text>}
                </View>
                <Text style={s.body}>{item.summary}</Text>
                {item.url ? <Text style={s.link} numberOfLines={1} onPress={() => Linking.openURL(item.url!)}>{item.url}</Text> : null}
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

function Act({ icon, label, color, onPress, testID }: { icon: IconName; label: string; color: string; onPress: () => void; testID: string }) {
  const s = useStyles();
  return (
    <Pressable onPress={onPress} style={[s.act, { borderColor: color }]} testID={testID}>
      <Icon name={icon} size={16} color={color} />
      <Text style={[s.actText, { color }]}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, gap: space.md, borderBottomWidth: 1, borderBottomColor: c.border },
  topRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  actions: { flexDirection: "row", gap: space.sm },
  act: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.pill, borderWidth: 1 },
  actText: { fontFamily: fonts.semibold, fontSize: 13 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  note: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17, marginBottom: space.sm },
  msg: { borderRadius: radius.md, padding: space.md, gap: 4, maxWidth: "92%" },
  out: { alignSelf: "flex-end", backgroundColor: c.brandTertiary },
  in: { alignSelf: "flex-start", backgroundColor: c.surface, borderWidth: 1, borderColor: c.border },
  meta: { fontFamily: fonts.medium, fontSize: 11, color: c.muted },
  body: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  link: { fontFamily: fonts.medium, fontSize: 12, color: c.brand },
}));
