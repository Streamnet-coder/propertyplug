import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { ActivityIndicator, Platform, Share, Text, View } from "react-native";

import { api, BACKEND_URL } from "@/src/api";
import { Button, Card, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { useBranding, useProject } from "@/src/queries";
import { shareProgressReport } from "@/src/report";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

export default function ShareReport() {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const { data: project } = useProject();
  const branding = useBranding();
  const router = useRouter();
  const [pdfBusy, setPdfBusy] = useState(false);
  const link = useQuery({ queryKey: ["share-link"], queryFn: () => api<{ url: string | null }>("/project/share") });
  const url = link.data?.url ?? null;

  const create = useMutation({
    mutationFn: () => api<{ url: string }>("/project/share", { body: { origin_url: BACKEND_URL } }),
    onSuccess: (d) => {
      queryClient.setQueryData(["share-link"], d);
      toast("Live link created");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const revoke = useMutation({
    mutationFn: () => api<{ url: null }>("/project/share", { method: "DELETE" }),
    onSuccess: (d) => {
      queryClient.setQueryData(["share-link"], d);
      toast("Link turned off. Old links no longer work", "info");
    },
  });

  const copy = async () => {
    await Clipboard.setStringAsync(url!);
    toast("Link copied");
  };
  const share = async () => {
    const message = `Live progress report for ${project?.name ?? "my project"}: ${url}`;
    if (Platform.OS === "web") return copy();
    await Share.share({ message, url: url! });
  };
  const pdf = async () => {
    setPdfBusy(true);
    try {
      await shareProgressReport();
    } catch (e: any) {
      toast(e?.message ?? "Could not create PDF", "error");
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <FormScreen title="Share progress report" testID="share-report-screen">
      <Card style={{ gap: space.md }}>
        <View style={s.row}>
          <View style={[s.icon, { backgroundColor: colors.surfaceTertiary }]}><Icon name="building-2" size={20} color={colors.onSurfaceSecondary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>Your branding</Text>
            <Text style={s.muted} testID="share-branding-summary">
              {branding.data?.company_name ? `${branding.data.company_name}${branding.data.logo_path ? " · logo added" : ""}` : "Add your logo & contact details to every report"}
            </Text>
          </View>
        </View>
        <Button small variant="outline" icon="pencil" title={branding.data?.company_name ? "Edit branding" : "Add branding"} onPress={() => router.push("/branding")} testID="share-branding-button" />
      </Card>
      <Card style={{ gap: space.md }}>
        <View style={s.row}>
          <View style={s.icon}><Icon name="link" size={20} color={colors.brand} /></View>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>Live link for lenders & buyers</Text>
            <Text style={s.muted}>Opens in any browser, no app needed. Always shows the latest budget, milestones and photos.</Text>
          </View>
        </View>
        {link.isLoading ? (
          <ActivityIndicator color={colors.brand} />
        ) : url ? (
          <>
            <View style={s.urlBox}>
              <Text style={s.url} numberOfLines={2} selectable testID="share-link-url">{url}</Text>
            </View>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="secondary" icon="share-2" title="Share" onPress={share} style={{ flex: 1 }} testID="share-link-share-button" />
              <Button small variant="outline" icon="copy" title="Copy" onPress={copy} style={{ flex: 1 }} testID="share-link-copy-button" />
            </View>
            <Button small variant="ghost" icon="external-link" title="Preview what lenders see" onPress={() => WebBrowser.openBrowserAsync(url)} testID="share-link-preview-button" />
            <Button small variant="danger" icon="link-2-off" title="Turn off link" loading={revoke.isPending} onPress={() => revoke.mutate()} testID="share-link-revoke-button" />
          </>
        ) : (
          <Button icon="link" title="Create live link" loading={create.isPending} onPress={() => create.mutate()} testID="share-link-create-button" />
        )}
      </Card>
      <Card style={{ gap: space.md }}>
        <View style={s.row}>
          <View style={[s.icon, { backgroundColor: colors.orangeTint }]}><Icon name="file-text" size={20} color={colors.brandPrimary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>PDF snapshot</Text>
            <Text style={s.muted}>A PDF of today&apos;s figures and photos to attach to emails or finance applications.</Text>
          </View>
        </View>
        <Button variant="outline" icon="download" title="Create PDF" loading={pdfBusy} onPress={pdf} testID="share-pdf-button" />
      </Card>
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", gap: space.md, alignItems: "flex-start" },
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 18, marginTop: 2 },
  urlBox: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: space.md },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand },
}));
