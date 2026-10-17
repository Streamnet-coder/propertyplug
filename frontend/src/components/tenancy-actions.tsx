import { useMutation } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { Modal, Pressable, Share, Text, View } from "react-native";

import { api, BACKEND_URL, Tenancy } from "@/src/api";
import { Button, fonts, radius, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles } from "@/src/theme";
import { useToast } from "@/src/toast";

/** Per-tenancy actions: annual statement, private tenant portal link, renew. */
export function TenancyActions({ t, year, onRenew }: { t: Tenancy; year: number; onRenew: () => void }) {
  const s = useStyles();
  const toast = useToast();
  const [portal, setPortal] = useState(false);

  const statement = useMutation({
    mutationFn: () => api(`/rentals/tenancies/${t.id}/statement`, { body: { year } }),
    onSuccess: () => toast(`${year} statement emailed to ${t.tenant_name}`),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const create = useMutation({
    mutationFn: () => api<{ url: string }>(`/rentals/tenancies/${t.id}/portal`, { body: { origin_url: BACKEND_URL } }),
    onSuccess: async () => { await invalidate("rentals"); setPortal(true); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const revoke = useMutation({
    mutationFn: () => api(`/rentals/tenancies/${t.id}/portal`, { method: "DELETE" }),
    onSuccess: async () => { await invalidate("rentals"); setPortal(false); toast("Tenant link turned off", "info"); },
  });
  const msg = (url: string) => `Hi ${t.tenant_name}, here is your private tenant portal: rent history, receipts, tenancy terms and repair reporting. ${url}`;

  return (
    <View style={{ gap: space.sm }}>
      <View style={{ flexDirection: "row", gap: space.sm }}>
        <Button small variant="outline" icon="file-text" title={`${year} statement`} style={{ flex: 1 }} disabled={!t.tenant_email} loading={statement.isPending} onPress={() => statement.mutate()} testID={`tenancy-statement-${t.id}`} />
        <Button small variant="outline" icon="link" title="Tenant portal" style={{ flex: 1 }} loading={create.isPending} onPress={() => (t.portal_url ? setPortal(true) : create.mutate())} testID={`tenancy-portal-${t.id}`} />
      </View>
      <Button small variant="outline" icon="refresh-cw" title="Renew / extend" onPress={onRenew} testID={`tenancy-renew-${t.id}`} />

      <Modal visible={portal && !!t.portal_url} transparent animationType="fade" onRequestClose={() => setPortal(false)}>
        <Pressable style={s.overlay} onPress={() => setPortal(false)}>
          <Pressable style={s.sheet} onPress={() => {}} testID="tenant-portal-sheet">
            <Text style={s.title}>Tenant portal for {t.tenant_name}</Text>
            <Text style={s.muted}>View-only page with tenancy terms, rent schedule, receipts and deposit status. Tenants can report repairs, which land in your snagging list.</Text>
            <Text style={s.url} numberOfLines={1} selectable testID="tenant-portal-url">{t.portal_url}</Text>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="outline" icon="copy" title="Copy" style={{ flex: 1 }} onPress={async () => { await Clipboard.setStringAsync(t.portal_url!); toast("Link copied"); }} testID="tenant-portal-copy" />
              <Button small variant="secondary" icon="share-2" title="Share" style={{ flex: 1 }} onPress={() => Share.share({ message: msg(t.portal_url!), url: t.portal_url! })} testID="tenant-portal-share" />
            </View>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Button small variant="ghost" icon="external-link" title="Preview" style={{ flex: 1 }} onPress={() => WebBrowser.openBrowserAsync(t.portal_url!)} testID="tenant-portal-preview" />
              <Button small variant="ghost" icon="link-2-off" title="Turn off" style={{ flex: 1 }} loading={revoke.isPending} onPress={() => revoke.mutate()} testID="tenant-portal-revoke" />
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

/** Email every tenant (with an email) their rent statement for the selected year. */
export function SendAllStatements({ year }: { year: number }) {
  const toast = useToast();
  const send = useMutation({
    mutationFn: () => api<{ sent: number; failed: number; skipped: number; no_email: number }>("/rentals/statements", { body: { year } }),
    onSuccess: (r) => toast(r.sent ? `${r.sent} statement${r.sent === 1 ? "" : "s"} emailed${r.failed ? ` · ${r.failed} failed` : ""}` : "No statements to send for this year", r.sent ? "success" : "info"),
    onError: (e: Error) => toast(e.message, "error"),
  });
  return <Button small variant="ghost" icon="mails" title={`Send ${year} statements to all tenants`} loading={send.isPending} onPress={() => send.mutate()} style={{ marginBottom: space.md }} testID="send-all-statements" />;
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, paddingBottom: space.xxl, gap: space.md },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand, backgroundColor: c.surfaceSecondary, padding: space.md, borderRadius: 10 },
}));
