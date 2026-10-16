import { useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Button, Chip, Field, fonts, space } from "@/src/components/ui";
import { useTheme } from "@/src/theme";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const plus = (days: number) => { const d = new Date(); d.setDate(d.getDate() + days); return iso(d); };
const PRESETS = [{ l: "30 days", d: 30 }, { l: "90 days", d: 90 }, { l: "6 months", d: 182 }, { l: "1 year", d: 365 }];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const fmtEnd = (v: string) => new Date(`${v}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Remount with key={value} to reset after the saved value changes. End-date chooser: quick presets, a typed date, or no end date. `onSave` is used for existing members (explicit save). */
export function AccessEndPicker({ value, onChange, onSave, saving, testID }: { value: string | null; onChange?: (v: string | null) => void; onSave?: (v: string | null) => void; saving?: boolean; testID: string }) {
  const { colors } = useTheme();
  const [text, setText] = useState(value ?? "");
  const pick = (v: string | null) => { setText(v ?? ""); onChange?.(v); };
  const bad = text.trim() !== "" && (!DATE_RE.test(text.trim()) || text.trim() < iso(new Date()));
  const dirty = (text.trim() || null) !== value;

  return (
    <View style={{ gap: space.sm }} testID={testID}>
      <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceSecondary }}>Access ends</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
        <Chip label="No end date" selected={!text.trim()} onPress={() => pick(null)} testID={`${testID}-none`} />
        {PRESETS.map((p) => (
          <Chip key={p.d} label={p.l} selected={text === plus(p.d)} onPress={() => pick(plus(p.d))} testID={`${testID}-${p.d}`} />
        ))}
      </ScrollView>
      <Field label="Or pick a date" value={text} onChangeText={(v) => { setText(v); if (!v.trim()) onChange?.(null); else if (DATE_RE.test(v.trim())) onChange?.(v.trim()); }} placeholder="YYYY-MM-DD" testID={`${testID}-input`} />
      {bad && <Text style={{ color: colors.error, fontFamily: fonts.medium, fontSize: 12 }} testID={`${testID}-error`}>Enter a date from today onwards as YYYY-MM-DD</Text>}
      {text.trim() !== "" && !bad && <Text style={{ fontFamily: fonts.regular, fontSize: 12, color: colors.muted }}>Access stops automatically after {fmtEnd(text.trim())}.</Text>}
      {onSave && dirty && <Button small title="Save end date" loading={saving} disabled={bad} onPress={() => onSave(text.trim() || null)} testID={`${testID}-save`} />}
    </View>
  );
}
