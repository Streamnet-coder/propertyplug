import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ActivityIndicator, Text, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { BrandLogo } from "@/src/components/brand";
import { Button, Card, fonts, Icon, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

type Info = { owner_name: string; role: "co_owner" | "manager"; project_names: string[] | null; money_access: boolean; expires_at: string };

/** Landing screen for a shareable co-owner / manager invite link. */
export default function JoinScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { user, loading, refresh } = useAuth();
  const info = useQuery({ queryKey: ["join", token], queryFn: () => api<Info>(`/join/${token}`), retry: false });

  const accept = useMutation({
    mutationFn: () => api<{ owner_name: string }>(`/join/${token}`, { method: "POST" }),
    onSuccess: async (r) => {
      await refresh();
      await queryClient.invalidateQueries();
      toast(`You now have access to ${r.owner_name}'s projects`);
      router.replace("/(tabs)");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const i = info.data;
  const next = `/join/${token}`;
  return (
    <View style={s.root} testID="join-screen">
      <View style={{ alignItems: "center", marginBottom: space.xl }}><BrandLogo /></View>
      {info.isLoading || loading ? (
        <ActivityIndicator color={colors.brand} />
      ) : info.isError || !i ? (
        <Card style={{ gap: space.md, alignItems: "center" }} testID="join-invalid">
          <Icon name="link-2-off" size={32} color={colors.error} />
          <Text style={s.title}>Invite link not available</Text>
          <Text style={[s.muted, { textAlign: "center" }]}>{(info.error as Error)?.message ?? "Ask the project owner for a new link."}</Text>
          <Button title="Go to PropertyPlug" variant="outline" onPress={() => router.replace("/")} testID="join-home-button" />
        </Card>
      ) : (
        <Card style={{ gap: space.md }} testID="join-card">
          <Text style={s.title}>{i.owner_name} invited you</Text>
          <Text style={s.body} testID="join-scope">
            {i.role === "co_owner"
              ? i.project_names ? `Become a co-owner with full access to: ${i.project_names.join(", ")}.` : "Become a co-owner of all their current and future projects."
              : `Become manager of: ${(i.project_names ?? []).join(", ")}.`}
          </Text>
          <Text style={s.muted} testID="join-money">
            {i.money_access ? "Full access including budgets, rent and reports." : "Day-to-day tasks only: timeline, snags, photos, documents and team. Money figures stay private."}
          </Text>
          <Text style={s.muted}>Link expires {i.expires_at.slice(0, 10)} and can be used once.</Text>
          {user ? (
            <>
              <Button title="Accept invite" icon="check" loading={accept.isPending} onPress={() => accept.mutate()} testID="join-accept-button" />
              <Text style={[s.muted, { textAlign: "center" }]}>Signed in as {user.email}</Text>
            </>
          ) : (
            <>
              <Button title="Create free account" icon="user-plus" onPress={() => router.push({ pathname: "/auth", params: { mode: "register", next } })} testID="join-register-button" />
              <Button title="I already have an account" variant="outline" onPress={() => router.push({ pathname: "/auth", params: { mode: "login", next } })} testID="join-login-button" />
            </>
          )}
        </Card>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary, padding: space.lg, justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 20, color: c.onSurface },
  body: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface, lineHeight: 21 },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
}));
