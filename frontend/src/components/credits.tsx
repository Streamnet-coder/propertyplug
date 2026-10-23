import { useQuery } from "@tanstack/react-query";
import * as WebBrowser from "expo-web-browser";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { api, onOutOfCredits } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { Listing } from "@/src/listings";
import { makeStyles, useTheme } from "@/src/theme";

export type Credits = { unlimited: boolean; allowance: number; used: number; remaining: number; resets_on: string; costs: { tool: string; cost: number }[] };

export function useCredits() {
  const { user } = useAuth();
  return useQuery({ queryKey: ["credits"], queryFn: () => api<Credits>("/credits"), enabled: !!user, staleTime: 30_000 });
}

/** Small "73 credits" pill for Basic users; tapping opens the upgrade screen. */
export function CreditsPill() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useCredits();
  if (!q.data || q.data.unlimited) return null;
  const low = q.data.remaining < 20;
  return (
    <Pressable onPress={() => { tap(); router.push("/profile"); }} style={[s.pill, low && { backgroundColor: colors.orangeTint }]} testID="credits-pill" accessibilityLabel="Free credits left">
      <Icon name="coins" size={14} color={low ? colors.brandPrimary : colors.brand} />
      <Text style={[s.pillText, low && { color: colors.brandPrimary }]}>{q.data.remaining} credits</Text>
    </Pressable>
  );
}

/** Global prompt shown whenever the backend says the month's free credits are used up (HTTP 402). */
export function CreditsPrompt() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => onOutOfCredits(setMsg), []);
  return (
    <Modal visible={!!msg} transparent animationType="fade" onRequestClose={() => setMsg(null)}>
      <Pressable style={s.overlay} onPress={() => setMsg(null)}>
        <Pressable style={s.card} onPress={() => {}} testID="credits-prompt">
          <View style={s.icon}><Icon name="crown" size={26} color={colors.brandPrimary} /></View>
          <Text style={s.title}>Out of free credits</Text>
          <Text style={s.body}>{msg}</Text>
          <Button title="Upgrade to Pro" icon="crown" onPress={() => { setMsg(null); router.push("/profile"); }} testID="credits-upgrade-button" />
          <Button title="Not now" variant="ghost" onPress={() => setMsg(null)} testID="credits-dismiss-button" />
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** Row of buttons opening live listings on Rightmove, Zoopla and OnTheMarket. */
export function ListingButtons({ links, title, testID }: { links: Listing[]; title: string; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ gap: space.sm }} testID={testID}>
      <Text style={s.label}>{title}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
        {links.map((l) => (
          <Pressable key={l.id} onPress={() => { tap(); WebBrowser.openBrowserAsync(l.url); }} style={({ pressed }) => [s.link, pressed && { opacity: 0.8 }]} testID={`${testID}-${l.id}`}>
            <Text style={s.linkText}>{l.label}</Text>
            <Icon name="external-link" size={14} color={colors.brand} />
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  pill: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 36, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.brandTertiary },
  pillText: { fontFamily: fonts.bold, fontSize: 12, color: c.brand },
  overlay: { flex: 1, backgroundColor: c.overlay, alignItems: "center", justifyContent: "center", padding: space.xl },
  card: { width: "100%", maxWidth: 420, backgroundColor: c.surface, borderRadius: radius.lg, padding: space.xl, gap: space.md, alignItems: "stretch" },
  icon: { alignSelf: "center", width: 56, height: 56, borderRadius: 28, backgroundColor: c.orangeTint, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.extrabold, fontSize: 20, color: c.onSurface, textAlign: "center" },
  body: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurfaceTertiary, textAlign: "center", lineHeight: 20 },
  label: { fontFamily: fonts.semibold, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  link: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  linkText: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
}));
