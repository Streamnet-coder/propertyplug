import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Linking, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Button, Chip, EmptyState, fonts, Icon, IconName, radius, space, tap } from "@/src/components/ui";
import { Stars, useTrustedTrades } from "@/src/components/rating";
import { invalidate, useContacts, useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Trade = { osm_id: string; name: string; trade: string; phone?: string | null; email?: string | null; website?: string | null; address: string; distance_km: number };
type SearchRes = { postcode: string; trade: string; results: Trade[]; attribution: string };

const TRADES: { key: string; label: string; role: string }[] = [
  { key: "electrician", label: "Electricians", role: "Electrician" },
  { key: "plumber", label: "Plumbers", role: "Plumber & Heating" },
  { key: "builder", label: "Builders", role: "General Builder" },
  { key: "carpenter", label: "Carpenters", role: "Carpenter & Joiner" },
  { key: "painter", label: "Decorators", role: "Painter & Decorator" },
  { key: "roofer", label: "Roofers", role: "Roofer" },
];
const UK_PC = /([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})/i;

export default function TradesFinder() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const s = useStyles();
  const trusted = useTrustedTrades();
  const { colors } = useTheme();
  const toast = useToast();
  const { data: project } = useProject();
  const team = useContacts("trade");
  const [postcode, setPostcode] = useState(() => project?.address.match(UK_PC)?.[1]?.toUpperCase() ?? "");
  const [trade, setTrade] = useState("electrician");
  const [invited, setInvited] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const pc = project?.address.match(UK_PC)?.[1]?.toUpperCase();
    if (pc) setPostcode((cur) => cur || pc);
  }, [project?.address]);

  const search = useMutation({
    mutationFn: (t: string) => api<SearchRes>(`/trades/search?postcode=${encodeURIComponent(postcode.trim())}&trade=${t}`),
  });

  const run = (t = trade) => {
    if (!postcode.trim()) return toast("Enter a postcode first", "error");
    setTrade(t);
    search.mutate(t);
  };

  const onTeam = (t: Trade) => invited[t.osm_id] || !!team.data?.some((c) => c.name.toLowerCase() === t.name.toLowerCase());

  const addToTeam = async (t: Trade) => {
    try {
      await api("/contacts", {
        body: { kind: "trade", name: t.name, role: TRADES.find((x) => x.key === t.trade)?.role ?? t.trade, phone: t.phone ?? "", email: t.email ?? "", status: "Invited" },
      });
      setInvited((x) => ({ ...x, [t.osm_id]: true }));
      invalidate("contacts");
      toast(`${t.name} added to your team`);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const inviteMsg = (t: Trade) =>
    `Hi ${t.name}, I found you on PropertyPlug. I'm looking for a ${TRADES.find((x) => x.key === t.trade)?.role.toLowerCase()} for a project${project ? ` at ${project.address}` : ""}. Could you quote?`;
  const open = (url: string) => Linking.openURL(url).catch(() => toast("Can't open this on your device", "error"));

  const act = (icon: IconName, color: string, onPress: () => void, testID: string) => (
    <Pressable testID={testID} onPress={() => { tap(); onPress(); }} style={({ pressed }) => [s.actBtn, { borderColor: color }, pressed && { opacity: 0.6 }]}>
      <Icon name={icon} size={18} color={color} />
    </Pressable>
  );

  return (
    <View style={s.root} testID="trades-finder-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={s.topRow}>
          <Pressable testID="trades-finder-back-button" onPress={() => router.back()} style={s.back} hitSlop={10}>
            <Icon name="arrow-left" size={22} />
          </Pressable>
          <Text style={s.headerTitle}>Find local trades</Text>
          <View style={{ width: 44 }} />
        </View>
        <View style={s.searchRow}>
          <View style={s.inputBox}>
            <Icon name="map-pin" size={18} color={colors.muted} />
            <TextInput
              value={postcode}
              onChangeText={setPostcode}
              placeholder="UK postcode e.g. NG3 5AP"
              placeholderTextColor={colors.muted}
              autoCapitalize="characters"
              returnKeyType="search"
              onSubmitEditing={() => run()}
              style={s.input}
              testID="trades-postcode-input"
            />
          </View>
          <Button small title="Search" onPress={() => run()} loading={search.isPending} testID="trades-search-button" style={{ minHeight: 48 }} />
        </View>
      </View>
      <View style={s.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} keyboardShouldPersistTaps="handled">
          {TRADES.map((t) => (
            <Chip key={t.key} label={t.label} selected={trade === t.key} onPress={() => (postcode.trim() ? run(t.key) : setTrade(t.key))} testID={`trades-filter-${t.key}`} />
          ))}
        </ScrollView>
      </View>

      {!search.data && !search.isPending && (trusted.data ?? []).filter((x) => x.avg >= 4).length > 0 && (
        <View style={s.trusted} testID="trusted-trades-section">
          <Text style={s.trustedTitle}>Your trusted trades</Text>
          {(trusted.data ?? []).filter((x) => x.avg >= 4).slice(0, 5).map((x) => (
            <View key={x.name} style={s.trustedRow} testID={`trusted-${x.name.replace(/\s+/g, "-").toLowerCase()}`}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.trustedName}>{x.name}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <Stars value={x.avg} size={12} />
                  <Text style={s.muted}>{x.avg.toFixed(1)} · {x.count} job{x.count === 1 ? "" : "s"}{x.top_tags.length ? ` · ${x.top_tags.join(", ")}` : ""}</Text>
                </View>
              </View>
              {x.phone ? (
                <Pressable onPress={() => open(`tel:${x.phone}`)} style={s.trustedCall} hitSlop={6} testID={`trusted-call-${x.name.replace(/\s+/g, "-").toLowerCase()}`}>
                  <Icon name="phone" size={16} color={colors.brand} />
                </Pressable>
              ) : null}
            </View>
          ))}
        </View>
      )}

      {search.isPending ? (
        <View style={s.center}>
          <ActivityIndicator color={colors.brand} />
          <Text style={s.muted}>Searching OpenStreetMap near {postcode.toUpperCase()}…</Text>
        </View>
      ) : search.isError ? (
        <View style={s.center}>
          <EmptyState icon="circle-alert" title="Search failed" subtitle={(search.error as Error).message} testID="trades-error" />
          <Button small title="Try again" onPress={() => run()} testID="trades-retry-button" />
        </View>
      ) : !search.data ? (
        <EmptyState icon="search" title="Find trades near your project" subtitle="Search by postcode for electricians, plumbers, builders and more within ~8km." testID="trades-intro" />
      ) : (
        <FlatList
          data={search.data.results}
          keyExtractor={(t) => t.osm_id}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ padding: space.lg, gap: space.md, paddingBottom: insets.bottom + space.xl }}
          ListHeaderComponent={<Text style={s.muted} testID="trades-result-count">{search.data.results.length} found near {search.data.postcode}</Text>}
          ListFooterComponent={
            <Pressable onPress={() => open("https://www.openstreetmap.org/copyright")} testID="osm-attribution">
              <Text style={[s.muted, { textAlign: "center", marginTop: space.sm }]}>{search.data.attribution}</Text>
            </Pressable>
          }
          ListEmptyComponent={<EmptyState icon="hard-hat" title="No listed trades nearby" subtitle="Try another trade or a nearby postcode. Listings come from OpenStreetMap." testID="trades-empty" />}
          renderItem={({ item, index }) => {
            const added = onTeam(item);
            const wa = item.phone?.replace(/[^\d]/g, "").replace(/^0/, "44");
            return (
              <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 40)} style={s.card} testID={`trade-result-${index}`}>
                <View style={{ flexDirection: "row", gap: space.md, alignItems: "flex-start" }}>
                  <View style={s.avatar}><Icon name="hard-hat" size={20} color={colors.brand} /></View>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={s.name}>{item.name}</Text>
                    {item.address ? <Text style={s.muted} numberOfLines={2}>{item.address}</Text> : null}
                    <Text style={s.distance}>{item.distance_km.toFixed(1)} km away</Text>
                  </View>
                </View>
                <View style={s.actions}>
                  {item.phone ? act("phone", colors.brand, () => open(`tel:${item.phone}`), `trade-call-${index}`) : null}
                  {wa ? act("message-circle", colors.success, () => open(`https://wa.me/${wa}?text=${encodeURIComponent(inviteMsg(item))}`), `trade-whatsapp-${index}`) : null}
                  {item.email ? act("mail", colors.accent, () => open(`mailto:${item.email}?subject=${encodeURIComponent("Quote request")}&body=${encodeURIComponent(inviteMsg(item))}`), `trade-email-${index}`) : null}
                  {item.website ? act("globe", colors.muted, () => open(item.website!.startsWith("http") ? item.website! : `https://${item.website}`), `trade-website-${index}`) : null}
                  <View style={{ flex: 1 }} />
                  <Button
                    small
                    variant={added ? "outline" : "primary"}
                    icon={added ? "check" : "user-plus"}
                    title={added ? "On team" : "Invite"}
                    disabled={added}
                    onPress={() => addToTeam(item)}
                    testID={`trade-invite-${index}`}
                  />
                </View>
                {!item.phone && !item.email ? <Text style={s.muted}>No contact details listed. Add to team, then fill them in later.</Text> : null}
              </Animated.View>
            );
          }}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  trusted: { margin: space.lg, marginBottom: 0, padding: space.md, borderRadius: radius.md, backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, gap: space.sm },
  trustedTitle: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  trustedRow: { flexDirection: "row", alignItems: "center", gap: space.md, paddingTop: space.sm, borderTopWidth: 1, borderTopColor: c.divider },
  trustedName: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  trustedCall: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { paddingHorizontal: space.lg, paddingBottom: space.md, backgroundColor: c.surface, gap: space.md },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.bold, fontSize: 17, color: c.onSurface },
  searchRow: { flexDirection: "row", gap: space.sm, alignItems: "center" },
  inputBox: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceSecondary,
    paddingHorizontal: space.md,
  },
  input: { flex: 1, fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface, minHeight: 46 },
  chipRow: { height: 56, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, justifyContent: "center" },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md, padding: space.lg },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  card: { backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  distance: { fontFamily: fonts.semibold, fontSize: 12, color: c.brand, marginTop: 2 },
  actions: { flexDirection: "row", alignItems: "center", gap: space.sm },
  actBtn: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface },
}));
