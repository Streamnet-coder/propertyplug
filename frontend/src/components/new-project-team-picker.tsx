import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { accessLabel } from "@/src/components/invite-links";
import { fonts, Icon, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Person = { id: string; email: string; name: string | null; role: "co_owner" | "manager"; project_ids: string[] | null; project_names: string[] | null; auto_add: boolean };

/** New project: tick which chosen-projects co-owners/managers also get it (pre-ticked when they have auto-add on). */
export function NewProjectTeamPicker({ onChange }: { onChange: (ids: string[]) => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["co-owners"], queryFn: () => api<Person[]>("/co-owners") });
  const scoped = (q.data ?? []).filter((c) => c.project_ids !== null);
  const everyone = (q.data ?? []).filter((c) => c.project_ids === null);
  const [picked, setPicked] = useState<string[] | null>(null);

  useEffect(() => {
    if (q.data && picked === null) {
      const d = q.data.filter((c) => c.project_ids !== null && c.auto_add).map((c) => c.id);
      setPicked(d);
      onChange(d);
    }
  }, [q.data, picked, onChange]);

  if (!q.data?.length) return null;
  const toggle = (id: string) => {
    tap();
    const next = (picked ?? []).includes(id) ? (picked ?? []).filter((x) => x !== id) : [...(picked ?? []), id];
    setPicked(next);
    onChange(next);
  };

  return (
    <View style={{ gap: space.sm }} testID="new-project-team">
      <Text style={s.label}>Share with your team</Text>
      {everyone.length > 0 && (
        <Text style={s.muted} testID="new-project-team-all">
          {everyone.map((c) => c.name || c.email).join(", ")} {everyone.length === 1 ? "has" : "have"} access to all projects, so they get this one automatically.
        </Text>
      )}
      {scoped.map((c) => {
        const on = (picked ?? []).includes(c.id);
        return (
          <Pressable key={c.id} onPress={() => toggle(c.id)} style={[s.row, on && { borderColor: colors.brand }]} accessibilityRole="checkbox" accessibilityState={{ checked: on }} testID={`new-project-team-${c.id}`}>
            <View style={[s.box, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>{on && <Icon name="check" size={14} color={colors.onBrand} />}</View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{c.name || c.email}</Text>
              <Text style={s.muted} numberOfLines={1}>{accessLabel(c)}{c.auto_add ? " · auto-add on" : ""}</Text>
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.bold, fontSize: 16, color: c.onSurface, marginTop: space.sm },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, lineHeight: 17 },
  name: { fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.md, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, minHeight: 52 },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 1.5, borderColor: c.border, alignItems: "center", justifyContent: "center" },
}));
