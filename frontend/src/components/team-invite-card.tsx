import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { useAuth } from "@/src/auth";
import { InviteLinks } from "@/src/components/invite-links";
import { Button, Card, Chip, fonts, Icon, space } from "@/src/components/ui";
import { useProject } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

/** Quick team invites from the Share portal: a co-owner (all projects) or a manager for this project, via a shareable link. */
export function TeamInviteCard() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { user } = useAuth();
  const { data: project } = useProject();
  const [role, setRole] = useState<"co_owner" | "manager">("co_owner");
  const [money, setMoney] = useState(true);
  if (user?.acting_as || !project) return null; // only the owner can bring people in

  return (
    <Card style={{ gap: space.md }} testID="share-team-card">
      <View style={{ flexDirection: "row", gap: space.md, alignItems: "center" }}>
        <View style={s.badge}><Icon name="users" size={20} color={colors.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Bring in your team</Text>
          <Text style={s.muted}>Invite a co-owner or assign a manager to {project.name}</Text>
        </View>
      </View>
      <View style={s.row}>
        <Chip label="Invite co-owner" icon="users" selected={role === "co_owner"} onPress={() => setRole("co_owner")} testID="share-team-role-co-owner" />
        <Chip label="Assign manager" icon="briefcase" selected={role === "manager"} onPress={() => setRole("manager")} testID="share-team-role-manager" />
      </View>
      <Text style={s.muted} testID="share-team-role-hint">
        {role === "co_owner" ? "Co-owners can see and edit all your projects." : `Managers only get access to ${project.name}.`}
      </Text>
      <View style={s.row}>
        <Chip label="Full access incl. money" icon="wallet" selected={money} onPress={() => setMoney(true)} testID="share-team-money-full" />
        <Chip label="Tasks only" icon="list-checks" selected={!money} onPress={() => setMoney(false)} testID="share-team-money-tasks" />
      </View>
      <InviteLinks projectIds={role === "manager" ? [project.id] : null} moneyAccess={money} disabled={false} />
      <Button small variant="ghost" icon="mail" title="Invite by email or manage team" onPress={() => router.push("/co-owners")} testID="share-team-manage" />
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  badge: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  row: { flexDirection: "row", gap: space.sm, flexWrap: "wrap" },
}));
