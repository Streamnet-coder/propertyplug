import { useMutation } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api, fileUrl, Snag } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { Button, Chip, Field, fonts, FormScreen, radius, space } from "@/src/components/ui";
import { invalidate, useContacts, useSnags } from "@/src/queries";
import { useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadAsset } from "@/src/upload";

const ROOMS = ["Kitchen", "Bathroom", "Living room", "Bedroom 1", "Bedroom 2", "Bedroom 3", "Hallway", "Landing", "Exterior", "Garden"];
const PRIOS = ["low", "medium", "high"] as const;

export default function SnagForm() {
  const params = useLocalSearchParams<{ id?: string; room?: string }>();
  const id = params.id;
  const router = useRouter();
  const toast = useToast();
  const { colors } = useTheme();
  const { data } = useSnags();
  const team = useContacts("trade");
  const existing = data?.find((x) => x.id === id);
  const [room, setRoom] = useState(params.room ?? "");
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState<Snag["priority"]>("medium");
  const [assignee, setAssignee] = useState("");
  const [photo, setPhoto] = useState<PickedAsset | null>(null);
  const [error, setError] = useState("");
  const label = { fontFamily: fonts.semibold, fontSize: 13, color: colors.onSurfaceTertiary };

  useEffect(() => {
    if (existing) {
      setRoom(existing.room);
      setDesc(existing.description);
      setPriority(existing.priority);
      setAssignee(existing.assignee);
    }
  }, [existing]);

  const finish = async (msg: string) => {
    await invalidate("snags");
    toast(msg);
    router.back();
  };

  const save = useMutation({
    mutationFn: async () => {
      if (id) return api(`/snags/${id}`, { method: "PUT", body: { room: room.trim(), description: desc.trim(), priority, assignee } });
      const storage_path = photo ? await uploadAsset(photo) : null;
      return api("/snags", { body: { room: room.trim(), description: desc.trim(), priority, assignee, storage_path } });
    },
    onSuccess: () => finish(id ? "Snag updated" : "Snag logged"),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({ mutationFn: () => api(`/snags/${id}`, { method: "DELETE" }), onSuccess: () => finish("Snag deleted") });

  const submit = () => {
    setError("");
    if (!room.trim() || !desc.trim()) return setError("Choose a room and describe the defect");
    save.mutate();
  };

  return (
    <FormScreen
      title={id ? "Edit snag" : "Log snag"}
      testID="snag-form-screen"
      footer={
        <>
          <Button title={id ? "Save snag" : "Log snag"} loading={save.isPending} onPress={submit} testID="snag-save-button" />
          {id && <Button variant="danger" icon="trash-2" title="Delete snag" loading={remove.isPending} onPress={() => remove.mutate()} testID="snag-delete-button" />}
        </>
      }
    >
      {id ? (
        existing?.storage_path ? (
          <Image source={{ uri: fileUrl(existing.storage_path) }} style={{ width: "100%", height: 200, borderRadius: radius.lg }} contentFit="cover" testID="snag-photo" />
        ) : null
      ) : (
        <PhotoPicker value={photo} onChange={setPhoto} hint="Snap the defect so trades know exactly what to fix. Access is only requested when you tap." />
      )}
      <View style={{ gap: space.sm }}>
        <Text style={label}>Room</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {ROOMS.map((r) => (
            <Chip key={r} label={r} selected={room === r} onPress={() => setRoom(r)} testID={`snag-form-room-${r.replace(/\s+/g, "-").toLowerCase()}`} />
          ))}
        </ScrollView>
        <Field label="Or type a room" value={room} onChangeText={setRoom} placeholder="e.g. Loft" testID="snag-room-input" />
      </View>
      <Field label="Defect" value={desc} onChangeText={setDesc} multiline placeholder="e.g. Gap in silicone around bath, cracked tile by door" testID="snag-description-input" />
      <View style={{ gap: space.sm }}>
        <Text style={label}>Priority</Text>
        <View style={{ flexDirection: "row", gap: space.sm }}>
          {PRIOS.map((p) => (
            <Chip key={p} label={p[0].toUpperCase() + p.slice(1)} selected={priority === p} onPress={() => setPriority(p)} testID={`snag-priority-${p}`} />
          ))}
        </View>
      </View>
      <Field label="Assigned trade (optional)" value={assignee} onChangeText={setAssignee} placeholder="e.g. Sajid Khan" testID="snag-assignee-input" />
      {(team.data ?? []).length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
          {team.data!.map((c) => (
            <Chip key={c.id} label={c.name} selected={assignee.toLowerCase() === c.name.toLowerCase()} onPress={() => setAssignee(c.name)} testID={`snag-assignee-chip-${c.id}`} />
          ))}
        </ScrollView>
      )}
      {existing?.fixed_by ? (
        <View style={{ gap: space.sm }} testID="snag-fix-evidence">
          <Text style={label}>Fixed by {existing.fixed_by}{existing.fix_note ? `: "${existing.fix_note}"` : ""}</Text>
          {existing.fix_photo_path ? (
            <Image source={{ uri: fileUrl(existing.fix_photo_path) }} style={{ width: "100%", height: 200, borderRadius: radius.lg }} contentFit="cover" testID="snag-fix-photo" />
          ) : null}
        </View>
      ) : null}
      {error ? <Text style={{ color: colors.error, fontFamily: fonts.medium }} testID="snag-form-error">{error}</Text> : null}
    </FormScreen>
  );
}
