import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { ActivityIndicator, Platform, Share, Text, View } from "react-native";

import { api, BACKEND_URL } from "@/src/api";
import { Button, Card, fonts, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export function DigestShareCard({ projectName }: { projectName?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const link = useQuery({ queryKey: ["digest-link"], queryFn: () => api<{ url: string | null }>("/digest/share") });
  const url = link.data?.url ?? null;
  const set = (d: { url: string | null }) => queryClient.setQueryData(["digest-link"], d);

  const create = useMutation({
    mutationFn: () => api<{ url: string }>("/digest/share", { body: { origin_url: BACKEND_URL } }),
    onSuccess: (d) => { set(d); toast("Weekly update link created"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const revoke = useMutation({
    mutationFn: () => api<{ url: null }>("/digest/share", { method: "DELETE" }),
    onSuccess: (d) => { set(d); toast("Link turned off", "info"); },
  });

  const copy = async () => { await Clipboard.setStringAsync(url!); toast("Link copied"); };
  const share = async () => {
    if (Platform.OS === "web") return copy();
    await Share.share({ message: `Weekly update for ${projectName ?? "our project"}: ${url}`, url: url! });
  };

  return (
    <Card style={{ gap: space.md }} testID="digest-share-card">
      <View style={{ flexDirection: "row", gap: space.md, alignItems: "flex-start" }}>
        <View style={s.icon}><Icon name="users" size={20} color={colors.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Share with partners</Text>
          <Text style={s.muted}>A read-only weekly update link for investors, lenders or your partner. Opens in any browser and always shows the latest week.</Text>
        </View>
      </View>
      {link.isLoading ? (
        <ActivityIndicator color={colors.brand} />
      ) : url ? (
        <>
          <View style={s.urlBox}><Text style={s.url} numberOfLines={2} selectable testID="digest-share-url">{url}</Text></View>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small variant="secondary" icon="share-2" title="Share" onPress={share} style={{ flex: 1 }} testID="digest-share-button" />
            <Button small variant="outline" icon="copy" title="Copy" onPress={copy} style={{ flex: 1 }} testID="digest-copy-button" />
          </View>
          <Button small variant="ghost" icon="external-link" title="Preview what partners see" onPress={() => WebBrowser.openBrowserAsync(url)} testID="digest-preview-button" />
          <Button small variant="danger" icon="link-2-off" title="Turn off link" loading={revoke.isPending} onPress={() => revoke.mutate()} testID="digest-revoke-button" />
        </>
      ) : (
        <Button icon="link" title="Create weekly update link" loading={create.isPending} onPress={() => create.mutate()} testID="digest-create-link-button" />
      )}
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 18, marginTop: 2 },
  urlBox: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand },
}));
