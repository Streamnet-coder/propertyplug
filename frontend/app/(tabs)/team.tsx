import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, Linking, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Contact, ContactKind } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Chip, EmptyState, fonts, Icon, IconName, LockedPro, ProBadge, radius, space, tap } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { invalidate, useContacts } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const SEGMENTS: { kind: ContactKind; label: string; pro: boolean }[] = [
  { kind: "trade", label: "Trades", pro: false },
  { kind: "subcontractor", label: "Subcontractors", pro: true },
  { kind: "stakeholder", label: "Stakeholders", pro: true },
];

function ActionBtn({ icon, color, onPress, testID }: { icon: IconName; color: string; onPress: () => void; testID: string }) {
  const s = useStyles();
  return (
    <Pressable testID={testID} onPress={() => { tap(); onPress(); }} style={({ pressed }) => [s.actBtn, { borderColor: color }, pressed && { opacity: 0.6 }]} hitSlop={4}>
      <Icon name={icon} size={18} color={color} />
    </Pressable>
  );
}

export default function Team() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const isPro = user?.plan === "pro";
  const [kind, setKind] = useState<ContactKind>("trade");
  const seg = SEGMENTS.find((x) => x.kind === kind)!;
  const locked = seg.pro && !isPro;
  const q = useContacts(kind, !locked);

  const del = useMutation({
    mutationFn: (id: string) => api(`/contacts/${id}`, { method: "DELETE" }),
    onSuccess: () => { invalidate("contacts"); toast("Contact removed"); },
  });

  const open = (url: string) => Linking.openURL(url).catch(() => toast("Can't open this on your device", "error"));

  const renderItem = ({ item, index }: { item: Contact; index: number }) => {
    const initials = item.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
    const wa = item.phone.replace(/[^\d]/g, "");
    return (
      <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 50)} style={s.row} testID={`contact-row-${item.id}`}>
        <View style={{ flexDirection: "row", gap: space.md, alignItems: "center" }}>
          <View style={[s.avatar, kind === "stakeholder" && { backgroundColor: colors.orangeTint }]}>
            <Text style={[s.initials, kind === "stakeholder" && { color: colors.brandPrimary }]}>{initials}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.name} numberOfLines={1}>{item.name}</Text>
            <Text style={s.role} numberOfLines={1}>{item.role}</Text>
          </View>
          {item.status && kind === "trade" ? (
            <View style={[s.status, item.status === "Assigned" && { backgroundColor: colors.brandTertiary }]}>
              <Text style={[s.statusText, item.status === "Assigned" && { color: colors.brand }]}>{item.status}</Text>
            </View>
          ) : null}
          {kind === "stakeholder" && item.cost ? <Text style={s.cost}>{item.cost}</Text> : null}
        </View>
        {kind === "subcontractor" && (
          <View style={s.schedule}>
            <Icon name="calendar-clock" size={14} color={colors.brand} />
            <View style={{ flex: 1 }}>
              <Text style={s.scheduleText}>{item.schedule}</Text>
              {item.status ? <Text style={s.role}>Last update: {item.status}</Text> : null}
            </View>
          </View>
        )}
        <View style={s.actions}>
          {item.phone ? <ActionBtn icon="phone" color={colors.brand} onPress={() => open(`tel:${item.phone}`)} testID={`contact-call-${item.id}`} /> : null}
          {item.phone ? <ActionBtn icon="message-circle" color={colors.success} onPress={() => open(`https://wa.me/${wa}`)} testID={`contact-whatsapp-${item.id}`} /> : null}
          {item.email ? <ActionBtn icon="mail" color={colors.accent} onPress={() => open(`mailto:${item.email}`)} testID={`contact-email-${item.id}`} /> : null}
          <View style={{ flex: 1 }} />
          <ActionBtn icon="trash-2" color={colors.muted} onPress={() => del.mutate(item.id)} testID={`contact-delete-${item.id}`} />
        </View>
      </Animated.View>
    );
  };

  return (
    <View style={s.root} testID="team-screen">
      <View style={[s.header, { paddingTop: insets.top + space.sm }]}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Team</Text>
          <Text style={s.role}>Trades, subcontractors & stakeholders</Text>
        </View>
        {!locked && (
          <Pressable testID="add-contact-button" onPress={() => { tap(); router.push({ pathname: "/contact-form", params: { kind } }); }} style={s.addBtn}>
            <Icon name="plus" size={22} color={colors.onBrandPrimary} />
          </Pressable>
        )}
      </View>
      <View style={s.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {SEGMENTS.map((g) => (
            <View key={g.kind} style={{ flexShrink: 0 }}>
              <Chip label={g.label} selected={kind === g.kind} onPress={() => setKind(g.kind)} testID={`team-segment-${g.kind}`} icon={g.pro && !isPro ? "lock" : undefined} />
            </View>
          ))}
        </ScrollView>
      </View>
      {locked ? (
        <View style={{ padding: space.lg }}>
          <LockedPro
            feature={seg.label}
            description={kind === "stakeholder" ? "Keep lenders, estate agents and solicitors linked to your deal with their fees." : "Share schedules with subcontractors and message them on WhatsApp from one portal."}
          />
        </View>
      ) : q.isLoading ? (
        <View style={s.center}><ActivityIndicator color={colors.brand} /></View>
      ) : q.isError ? (
        <View style={s.center}>
          <Text style={s.role}>Error loading contacts.</Text>
          <Button small title="Retry" onPress={() => q.refetch()} testID="team-retry-button" />
        </View>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: space.lg, paddingBottom: bottomChrome + space.xl, gap: space.md }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => invalidate("contacts")} tintColor={colors.brand} />}
          ListHeaderComponent={
            seg.pro ? (
              <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}><ProBadge /><Text style={s.role}>Pro portal</Text></View>
            ) : (
              <Pressable testID="trades-finder-banner" onPress={() => { tap(); router.push("/trades-finder"); }} style={s.finder}>
                <View style={s.finderIcon}><Icon name="search" size={20} color={colors.onBrand} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={s.finderTitle}>Find local trades</Text>
                  <Text style={s.finderSub}>Search electricians, plumbers & builders by postcode</Text>
                </View>
                <Icon name="chevron-right" size={20} color={colors.onBrand} />
              </Pressable>
            )
          }
          ListEmptyComponent={<EmptyState icon="hard-hat" title="No team members yet" subtitle="Add your first trade to call or WhatsApp them in one tap." testID="team-empty" />}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: space.lg, paddingBottom: space.sm, backgroundColor: c.surface },
  title: { fontFamily: fonts.extrabold, fontSize: 28, color: c.onSurface, letterSpacing: -0.5 },
  addBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  chipRow: { height: 56, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border, justifyContent: "center" },
  chips: { gap: space.sm, paddingHorizontal: space.lg, alignItems: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  row: { backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.lg, gap: space.md },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  initials: { fontFamily: fonts.bold, fontSize: 15, color: c.brand },
  name: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  role: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  status: { backgroundColor: c.orangeTint, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  statusText: { fontFamily: fonts.semibold, fontSize: 11, color: c.brandPrimary },
  cost: { fontFamily: fonts.bold, fontSize: 12, color: c.onSurfaceSecondary },
  schedule: { flexDirection: "row", gap: space.sm, backgroundColor: c.surfaceSecondary, padding: space.md, borderRadius: radius.sm },
  scheduleText: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceSecondary },
  actions: { flexDirection: "row", gap: space.sm, alignItems: "center" },
  actBtn: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface },
  finder: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.brand, padding: space.lg, borderRadius: radius.lg },
  finderIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
  finderTitle: { fontFamily: fonts.bold, fontSize: 16, color: c.onBrand },
  finderSub: { fontFamily: fonts.regular, fontSize: 12, color: c.onBrand, opacity: 0.85, marginTop: 2 },
}));
