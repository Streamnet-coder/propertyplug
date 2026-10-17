import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { Modal, Pressable, ScrollView, Share, Text, View } from "react-native";

import { api, BACKEND_URL, DocItem, Tenancy } from "@/src/api";
import { Button, fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
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
            <TenantDocsPicker t={t} />
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

/** Tick Document Library files to show on this tenant's portal (expiry dates are shown there). */
function TenantDocsPicker({ t }: { t: Tenancy }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ["documents"], queryFn: () => api<DocItem[]>("/documents") });
  const save = useMutation({
    mutationFn: (ids: string[]) => api(`/rentals/tenancies/${t.id}/documents`, { method: "PUT", body: { doc_ids: ids } }),
    onSuccess: () => invalidate("rentals"),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const shared = save.variables ?? t.shared_doc_ids;
  const toggle = (id: string) => { tap(); save.mutate(shared.includes(id) ? shared.filter((x) => x !== id) : [...shared, id]); };
  const docs = q.data ?? [];
  return (
    <View style={{ gap: space.xs }} testID="tenant-docs-picker">
      <Text style={s.label}>Documents on the portal ({shared.length})</Text>
      {docs.length === 0 ? (
        <Text style={s.muted} testID="tenant-docs-empty">Upload the tenancy agreement, gas safety certificate, EICR or EPC to the Document Library to share them here.</Text>
      ) : (
        <ScrollView style={{ maxHeight: 200 }} nestedScrollEnabled>
          {docs.map((d) => {
            const on = shared.includes(d.id);
            return (
              <Pressable key={d.id} onPress={() => toggle(d.id)} style={s.docRow} testID={`tenant-doc-${d.id}`} accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>{on && <Icon name="check" size={14} color={colors.onBrand} />}</View>
                <View style={{ flex: 1 }}>
                  <Text style={s.docTitle} numberOfLines={1}>{d.title}</Text>
                  <Text style={[s.muted, d.expiry_status === "expired" && { color: colors.error }, d.expiry_status === "soon" && { color: colors.warning }]}>
                    {d.doc_type}{d.expires_on ? ` · ${d.expiry_status === "expired" ? "expired" : "expires"} ${d.expires_on}` : ""}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
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
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  docRow: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.sm, minHeight: 44 },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: c.border, alignItems: "center", justifyContent: "center" },
  docTitle: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  url: { fontFamily: fonts.medium, fontSize: 13, color: c.brand, backgroundColor: c.surfaceSecondary, padding: space.md, borderRadius: 10 },
}));
