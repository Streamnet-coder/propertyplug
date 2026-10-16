import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Overdue = { id: string; title: string; name: string; company: string; days_waiting: number };

/** Dashboard nudge: stakeholder document requests waiting 3+ days. */
export function OverdueRequestsCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useQuery({ queryKey: ["portal-members", "doc-requests", "overdue"], queryFn: () => api<Overdue[]>("/portal-doc-requests/overdue") });
  const rows = q.data ?? [];
  if (!rows.length) return null;
  const oldest = rows[0];
  return (
    <Pressable onPress={() => { tap(); router.push("/portal-access"); }} style={({ pressed }) => [s.card, pressed && { opacity: 0.9 }]} testID="overdue-requests-card">
      <Icon name="file-clock" size={20} color={colors.brandPrimary} />
      <View style={{ flex: 1 }}>
        <Text style={s.title}>{rows.length} document request{rows.length === 1 ? "" : "s"} waiting</Text>
        <Text style={s.muted} numberOfLines={2} testID="overdue-requests-detail">
          {oldest.name}{oldest.company ? ` (${oldest.company})` : ""} asked for &quot;{oldest.title}&quot; {oldest.days_waiting} days ago{rows.length > 1 ? ` · +${rows.length - 1} more` : ""}
        </Text>
      </View>
      <Icon name="chevron-right" size={18} color={colors.muted} />
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.orangeTint, borderRadius: radius.lg, borderWidth: 1, borderColor: c.orangeBorder, padding: space.lg },
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.onSurfaceSecondary },
}));
