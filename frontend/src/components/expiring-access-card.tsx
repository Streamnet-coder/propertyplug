import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { fmtEnd } from "@/src/components/access-end-picker";
import { fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Expiring = { id: string; name: string; role: string; company: string; project_name: string; expires_on: string; expired: boolean; days_left: number };

const when = (e: Expiring) =>
  e.expired ? `Ended ${fmtEnd(e.expires_on)}` : e.days_left === 0 ? "Ends today" : e.days_left === 1 ? "Ends tomorrow" : `Ends ${new Date(`${e.expires_on}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}`;

/** Stakeholders whose portal access ends within 7 days (or ended in the last 7), across all projects, with one-tap +30 days. */
export function ExpiringAccessCard({ showProject = true, linkToPortal = false }: { showProject?: boolean; linkToPortal?: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const q = useQuery({ queryKey: ["portal-members", "expiring"], queryFn: () => api<Expiring[]>("/portal-members/expiring") });
  const extend = useMutation({
    mutationFn: (e: Expiring) => api<{ expires_on: string }>(`/portal-members/${e.id}/extend`, { body: { days: 30 } }),
    onSuccess: async (r, e) => {
      toast(`${e.name}'s access now runs until ${fmtEnd(r.expires_on)}`);
      await queryClient.invalidateQueries({ queryKey: ["portal-members"] });
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
  const rows = q.data ?? [];
  if (!rows.length) return null;
  const anyEnded = rows.some((r) => r.expired);

  return (
    <View style={[s.card, { borderColor: anyEnded ? colors.error : colors.brandPrimary }]} testID="expiring-access-card">
      <Pressable disabled={!linkToPortal} onPress={() => { tap(); router.push("/portal-access"); }} style={s.head} testID="expiring-access-open">
        <Icon name="user-round-x" size={18} color={anyEnded ? colors.error : colors.brandPrimary} />
        <Text style={s.title}>Portal access ending this week</Text>
        {linkToPortal && <Icon name="chevron-right" size={18} color={colors.muted} />}
      </Pressable>
      {rows.map((e) => (
        <View key={e.id} style={s.row} testID={`expiring-row-${e.id}`}>
          <View style={{ flex: 1 }}>
            <Text style={s.name} numberOfLines={1}>{e.name}{e.company ? ` · ${e.company}` : ""}</Text>
            <Text style={[s.muted, { color: e.expired ? colors.error : e.days_left <= 1 ? colors.brandPrimary : colors.muted }]} numberOfLines={1} testID={`expiring-when-${e.id}`}>
              {when(e)}{showProject && e.project_name ? ` · ${e.project_name}` : ""}
            </Text>
          </View>
          <Pressable onPress={() => { tap(); extend.mutate(e); }} disabled={extend.isPending} style={s.btn} hitSlop={6} testID={`expiring-extend-${e.id}`}>
            {extend.isPending && extend.variables?.id === e.id ? <ActivityIndicator size="small" color={colors.onBrand} /> : <Text style={s.btnText}>{e.expired ? "Restore +30d" : "+30 days"}</Text>}
          </Pressable>
        </View>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1.5, padding: space.lg, gap: space.md },
  head: { flexDirection: "row", alignItems: "center", gap: space.sm },
  title: { flex: 1, fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  btn: { minHeight: 40, minWidth: 92, paddingHorizontal: space.md, borderRadius: radius.pill, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  btnText: { fontFamily: fonts.bold, fontSize: 13, color: c.onBrand },
}));
