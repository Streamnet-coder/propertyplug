import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { gbp } from "@/src/api";
import { fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { useRentals } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

/** Dashboard entry to the rent & tenancy tracker with this year's headline numbers. */
export function RentalsCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useRentals(new Date().getFullYear());
  const sm = q.data?.summary;
  const tenants = q.data?.tenancies.filter((t) => t.status === "active").length ?? 0;
  return (
    <Pressable testID="rentals-card" onPress={() => { tap(); router.push("/rentals"); }} style={({ pressed }) => [s.card, pressed && { opacity: 0.9 }]}>
      <View style={s.icon}><Icon name="key-round" size={18} color={colors.brand} /></View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.title}>Rent & tenancy</Text>
        {sm && q.data!.tenancies.length ? (
          <Text style={s.muted} numberOfLines={1} testID="rentals-card-summary">
            {tenants} active · {gbp(sm.received)} in · net {gbp(sm.net)}{sm.arrears > 0 ? ` · ` : ""}
            {sm.arrears > 0 && <Text style={{ color: colors.error, fontFamily: fonts.semibold }}>{gbp(sm.arrears)} arrears</Text>}
          </Text>
        ) : (
          <Text style={s.muted}>Track tenants, rent received and letting costs</Text>
        )}
      </View>
      <Icon name="chevron-right" size={18} color={colors.muted} />
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  card: { flexDirection: "row", alignItems: "center", gap: space.md, backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: space.lg, marginTop: space.md },
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
}));
