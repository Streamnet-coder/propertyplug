import { useMutation } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { Button, Chip, Field, fonts, FormScreen, space } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadAsset } from "@/src/upload";

const PHASES = [
  { key: "before", label: "Before" },
  { key: "progress", label: "In progress" },
  { key: "after", label: "After" },
] as const;

export default function MediaForm() {
  const params = useLocalSearchParams<{ milestone_id?: string; phase?: string; stage?: string }>();
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const [title, setTitle] = useState(params.stage ?? "");
  const [phase, setPhase] = useState<"before" | "progress" | "after">((params.phase as "before" | "progress" | "after") || "progress");
  const [photo, setPhoto] = useState<PickedAsset | null>(null);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: async () => {
      const storage_path = await uploadAsset(photo!);
      return api("/media", { body: { title: title.trim() || "Site photo", phase, storage_path, milestone_id: params.milestone_id ?? null } });
    },
    onSuccess: async () => {
      await invalidate("media");
      toast("Photo uploaded");
      router.back();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <FormScreen
      title={params.stage ? `Photo: ${params.stage}` : "Upload site photo"}
      testID="media-form-screen"
      footer={<Button title="Upload photo" icon="upload" loading={save.isPending} onPress={() => (photo ? save.mutate() : setError("Please choose a photo first"))} testID="media-form-save-button" />}
    >
      <PhotoPicker value={photo} onChange={setPhoto} hint="Document progress with a photo. We'll ask for camera or gallery access only when you tap." />
      <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Kitchen strip-out" testID="media-title-input" />
      <View style={{ gap: space.sm }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary }}>Stage</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {PHASES.map((p) => (
            <Chip key={p.key} label={p.label} selected={phase === p.key} onPress={() => setPhase(p.key)} testID={`media-phase-${p.key}`} />
          ))}
        </ScrollView>
      </View>
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="media-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
