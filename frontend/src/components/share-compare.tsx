import { useMutation } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useState } from "react";
import { Share, Text, View } from "react-native";

import { api, BACKEND_URL, CompareLink, logMessage } from "@/src/api";
import { Button, Card, fonts, Icon, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

/** Create a public, branded before/after link clients & lenders can drag on any phone. */
export function ShareCompare({ beforeId, afterId, title }: { beforeId?: string; afterId?: string; title: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [link, setLink] = useState<CompareLink | null>(null);
  useEffect(() => setLink(null), [beforeId, afterId]);

  const create = useMutation({
    mutationFn: () => api<CompareLink>("/compare-links", { body: { before_id: beforeId, after_id: afterId, title, origin_url: BACKEND_URL } }),
    onSuccess: async (l) => {
      setLink(l);
      await Share.share({ message: `See the before & after: ${l.url}`, url: l.url }).catch(() => undefined);
      logMessage({ name: "Before & after link", channel: "share", kind: "compare_link", summary: title || "Before & after", url: l.url });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const revoke = useMutation({
    mutationFn: () => api(`/compare-links/${link!.id}`, { method: "DELETE" }),
    onSuccess: () => { setLink(null); toast("Link turned off", "info"); },
  });

  return (
    <Card style={{ gap: space.md }} testID="share-compare-card">
      <View style={{ flexDirection: "row", gap: space.md, alignItems: "center" }}>
        <View style={s.icon}><Icon name="link" size={18} color={colors.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Share this transformation</Text>
          <Text style={s.muted}>A branded link with the drag slider that works on any phone. No app needed.</Text>
        </View>
      </View>
      {link ? (
        <>
          <Text style={s.url} numberOfLines={1} selectable testID="share-compare-url">{link.url}</Text>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small variant="outline" icon="copy" title="Copy" style={{ flex: 1 }} onPress={async () => { await Clipboard.setStringAsync(link.url); toast("Link copied"); }} testID="share-compare-copy" />
            <Button small variant="secondary" icon="share-2" title="Share" style={{ flex: 1 }} onPress={() => Share.share({ message: `See the before & after: ${link.url}`, url: link.url })} testID="share-compare-share" />
          </View>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small variant="ghost" icon="external-link" title="Preview" style={{ flex: 1 }} onPress={() => WebBrowser.openBrowserAsync(link.url)} testID="share-compare-preview" />
            <Button small variant="ghost" icon="link-2-off" title="Turn off" style={{ flex: 1 }} loading={revoke.isPending} onPress={() => revoke.mutate()} testID="share-compare-revoke" />
          </View>
        </>
      ) : (
        <Button icon="share-2" title="Create share link" disabled={!beforeId || !afterId} loading={create.isPending} onPress={() => create.mutate()} testID="share-compare-create" />
      )}
    </Card>
  );
}

const useStyles = makeStyles((c) => ({
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand, backgroundColor: c.surfaceSecondary, padding: space.md, borderRadius: 10 },
}));
