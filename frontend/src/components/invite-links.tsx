import { useMutation, useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { Share, Text, View } from "react-native";

import { api, BACKEND_URL } from "@/src/api";
import { Button, Card, fonts, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles } from "@/src/theme";
import { useToast } from "@/src/toast";

type Link = { id: string; token: string; role: "co_owner" | "manager"; project_names: string[] | null; money_access: boolean; expires_at: string };
const urlFor = (t: string) => `${BACKEND_URL}/join/${t}`;

/** "Co-owner · all projects", "Co-owner · Flat 2, Mill House" or "Manager · Flat 2". */
export const accessLabel = (a: { role: "co_owner" | "manager"; project_names: string[] | null }) =>
  `${a.role === "co_owner" ? "Co-owner" : "Manager"} · ${a.project_names ? a.project_names.join(", ") : "all projects"}`;

/** Create one-person, 7-day invite links using the same role / projects / money choices as the email invite. */
export function InviteLinks({ projectIds, moneyAccess, disabled, role, autoAdd = false }: { projectIds: string[] | null; moneyAccess: boolean; disabled: boolean; role: "co_owner" | "manager"; autoAdd?: boolean }) {
  const s = useStyles();
  const toast = useToast();
  const links = useQuery({ queryKey: ["co-owner-links"], queryFn: () => api<Link[]>("/co-owner-links") });
  const share = (l: Link) =>
    Share.share({ message: `Join my projects on PropertyPlug: ${urlFor(l.token)}`, url: urlFor(l.token) }).catch(() => undefined);
  const create = useMutation({
    mutationFn: () => api<Link>("/co-owner-links", { body: { role, project_ids: projectIds, money_access: role === "co_owner" ? true : moneyAccess, auto_add: projectIds !== null && autoAdd } }),
    onSuccess: async (l) => {
      await queryClient.invalidateQueries({ queryKey: ["co-owner-links"] });
      share(l);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/co-owner-links/${id}`, { method: "DELETE" }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["co-owner-links"] }); toast("Invite link cancelled", "info"); },
  });

  return (
    <View style={{ gap: space.sm }}>
      <Button variant="secondary" icon="link" title="Create shareable invite link" disabled={disabled} loading={create.isPending} onPress={() => create.mutate()} testID="invite-link-create" />
      <Text style={s.muted}>No email needed: share it on WhatsApp or text. One person can use it, within 7 days.</Text>
      {(links.data ?? []).map((l) => (
        <Card key={l.id} style={{ gap: space.sm }} testID={`invite-link-${l.id}`}>
          <Text style={s.label}>{accessLabel(l)}{l.money_access ? "" : " · tasks only"}</Text>
          <Text style={s.url} numberOfLines={1} selectable>{urlFor(l.token)}</Text>
          <Text style={s.muted}>Expires {l.expires_at.slice(0, 10)} · not used yet</Text>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Button small variant="outline" icon="copy" title="Copy" style={{ flex: 1 }} onPress={async () => { await Clipboard.setStringAsync(urlFor(l.token)); toast("Link copied"); }} testID={`invite-link-copy-${l.id}`} />
            <Button small variant="outline" icon="share-2" title="Share" style={{ flex: 1 }} onPress={() => share(l)} testID={`invite-link-share-${l.id}`} />
            <Button small variant="ghost" icon="x" title="Cancel" style={{ flex: 1 }} loading={cancel.isPending && cancel.variables === l.id} onPress={() => cancel.mutate(l.id)} testID={`invite-link-cancel-${l.id}`} />
          </View>
        </Card>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.brand },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  url: { fontFamily: fonts.medium, fontSize: 12, color: c.onSurface, backgroundColor: c.surfaceSecondary, padding: space.sm, borderRadius: 8 },
}));
