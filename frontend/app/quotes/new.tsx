import { useMutation } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api, BACKEND_URL, QuoteRequest } from "@/src/api";
import { Button, Field, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate, useContacts } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";

export default function NewQuote() {
  const router = useRouter();
  const s = useStyles();
  const { colors } = useTheme();
  const trades = useContacts("trade");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState("");

  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const save = useMutation({
    mutationFn: () => api<QuoteRequest>("/quotes", { body: { title: title.trim(), description: desc.trim(), contact_ids: picked, origin_url: BACKEND_URL } }),
    onSuccess: async (q) => {
      await invalidate("quotes");
      router.replace(`/quotes/${q.id}`);
    },
    onError: (e: Error) => setError(e.message),
  });

  const submit = () => {
    setError("");
    if (!title.trim() || !desc.trim()) return setError("Add a title and describe the job");
    if (!picked.length) return setError("Pick at least one tradesperson");
    save.mutate();
  };

  return (
    <FormScreen
      title="New quote request"
      testID="quote-new-screen"
      footer={<Button title={`Create request${picked.length ? ` for ${picked.length}` : ""}`} loading={save.isPending} onPress={submit} testID="quote-create-button" />}
    >
      <Field label="Job title" value={title} onChangeText={setTitle} placeholder="e.g. Full rewire, 3-bed terrace" testID="quote-title-input" />
      <Field
        label="Job description"
        value={desc}
        onChangeText={setDesc}
        multiline
        placeholder="Scope, materials, access, timings… every trade gets the same brief so quotes are like-for-like."
        testID="quote-description-input"
      />
      <View style={{ gap: space.sm }}>
        <Text style={s.label}>Send to</Text>
        {trades.isLoading ? (
          <ActivityIndicator color={colors.brand} />
        ) : (
          (trades.data ?? []).map((c) => {
            const on = picked.includes(c.id);
            return (
              <Pressable key={c.id} testID={`quote-recipient-${c.id}`} onPress={() => { tap(); toggle(c.id); }} style={[s.row, on && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]}>
                <View style={[s.check, on && { backgroundColor: colors.brand, borderColor: colors.brand }]}>
                  {on && <Icon name="check" size={14} color={colors.onBrand} />}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.name}>{c.name}</Text>
                  <Text style={s.muted}>{c.role}{c.phone ? " · WhatsApp" : c.email ? " · Email" : ""}</Text>
                </View>
              </Pressable>
            );
          })
        )}
        <Pressable testID="quote-find-trades-link" onPress={() => router.push("/trades-finder")} style={s.find}>
          <Icon name="search" size={16} color={colors.brand} />
          <Text style={s.findText}>Find more local trades</Text>
        </Pressable>
      </View>
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="quote-form-error">{error}</Text> : null}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    padding: space.md,
    minHeight: 56,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surface,
  },
  check: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
  find: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: space.sm, minHeight: 44 },
  findText: { fontFamily: fonts.semibold, fontSize: 14, color: c.brand },
}));
