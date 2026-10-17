import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";

import { api } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { Button, Field, fonts, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadForm } from "@/src/utils/upload";

export type FixTarget = { id: string; title: string; kind: "snag" | "repair"; project_name: string };

/** Mark a snag or tenant repair fixed from My tasks, with an optional after photo and note. */
export function QuickFixSheet({ target, onClose }: { target: FixTarget | null; onClose: () => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [photo, setPhoto] = useState<PickedAsset | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setPhoto(null);
    setNote("");
    setError("");
  }, [target]);

  const fix = useMutation({
    mutationFn: () => {
      const path = `/inbox/snags/${target!.id}/fix`;
      if (photo) return uploadForm<{ ok: boolean }>(path, photo, { note: note.trim() });
      const form = new FormData();
      form.append("note", note.trim());
      return api<{ ok: boolean }>(path, { method: "POST", form });
    },
    onSuccess: async () => {
      await Promise.all(["inbox", "snags"].map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
      toast(target!.kind === "repair" ? "Repair fixed · tenant notified" : "Snag marked fixed");
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Modal visible={!!target} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={s.overlay} onPress={onClose}>
          {target && (
            <Pressable style={s.sheet} onPress={() => {}} testID="quick-fix-sheet">
              <ScrollView contentContainerStyle={{ gap: space.md }} keyboardShouldPersistTaps="handled">
                <View>
                  <Text style={s.title}>Mark {target.kind === "repair" ? "repair" : "snag"} fixed</Text>
                  <Text style={s.muted} numberOfLines={2}>{target.title} · {target.project_name}</Text>
                </View>
                <PhotoPicker value={photo} onChange={setPhoto} hint="Add an after photo (optional)" />
                <Field label="Note (optional)" value={note} onChangeText={setNote} placeholder="e.g. Replaced washer, tested" multiline testID="quick-fix-note-input" />
                {target.kind === "repair" && <Text style={s.muted}>The tenant will be emailed that their repair is fixed.</Text>}
                {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="quick-fix-error">{error}</Text> : null}
                <Button title="Mark fixed" icon="check" loading={fix.isPending} onPress={() => fix.mutate()} testID="quick-fix-confirm" />
              </ScrollView>
            </Pressable>
          )}
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  overlay: { flex: 1, backgroundColor: c.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, paddingBottom: space.xxl, maxHeight: "90%" },
  title: { fontFamily: fonts.bold, fontSize: 18, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted },
}));
