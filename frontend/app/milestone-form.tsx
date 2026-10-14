import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, Milestone } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { StagePhotos } from "@/src/components/stage-photos";
import { invalidate, useMilestones } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";

const STATUSES: { key: Milestone["status"]; label: string }[] = [
  { key: "todo", label: "To do" },
  { key: "in_progress", label: "In progress" },
  { key: "done", label: "Done" },
];

export default function MilestoneForm() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data } = useMilestones();
  const existing = data?.find((m) => m.id === id);
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<Milestone["status"]>("todo");
  const [error, setError] = useState("");

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      setDate(existing.target_date ?? "");
      setNotes(existing.notes);
      setStatus(existing.status);
    }
  }, [existing]);

  const done = async (msg: string) => {
    await invalidate("milestones", "project", "projects");
    toast(msg);
    router.back();
  };

  const save = useMutation({
    mutationFn: async () => {
      if (id) return api(`/milestones/${id}`, { method: "PUT", body: { name: name.trim(), target_date: date.trim() || null, notes, status } });
      const m = await api<Milestone>("/milestones", { body: { name: name.trim(), target_date: date.trim() || null } });
      if (notes || status !== "todo") await api(`/milestones/${m.id}`, { method: "PUT", body: { notes, status } });
      return m;
    },
    onSuccess: () => done(id ? "Stage updated" : "Stage added"),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api(`/milestones/${id}`, { method: "DELETE" }),
    onSuccess: () => done("Stage removed"),
  });

  const submit = () => {
    setError("");
    if (!name.trim()) return setError("Please enter a stage name");
    if (date.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(date.trim())) return setError("Use date format YYYY-MM-DD");
    save.mutate();
  };

  return (
    <FormScreen
      title={id ? "Edit stage" : "New stage"}
      testID="milestone-form-screen"
      footer={
        <>
          <Button title={id ? "Save stage" : "Add stage"} loading={save.isPending} onPress={submit} testID="milestone-save-button" />
          {id && <Button variant="danger" icon="trash-2" title="Delete stage" loading={remove.isPending} onPress={() => remove.mutate()} testID="milestone-delete-button" />}
        </>
      }
    >
      <Field label="Stage name" value={name} onChangeText={setName} placeholder="e.g. Second fix electrics" testID="milestone-name-input" />
      <Field label="Target date" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" testID="milestone-date-input" />
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Status</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {STATUSES.map((st) => (
            <Chip key={st.key} label={st.label} selected={status === st.key} onPress={() => setStatus(st.key)} testID={`milestone-status-chip-${st.key}`} />
          ))}
        </ScrollView>
      </View>
      <Field label="Notes" value={notes} onChangeText={setNotes} multiline placeholder="Inspections booked, snagging, who's on site…" testID="milestone-notes-input" />
      {id && existing ? <StagePhotos milestoneId={id} stage={existing.name} /> : null}
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="milestone-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
