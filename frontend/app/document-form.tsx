import { useMutation } from "@tanstack/react-query";
import * as DocumentPicker from "expo-document-picker";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { DocItem, DOC_TYPES, fileSize } from "@/src/api";
import { Button, Chip, Field, fonts, FormScreen, Icon, radius, space, tap } from "@/src/components/ui";
import { invalidate } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadForm } from "@/src/utils/upload";

const MAX = 20 * 1024 * 1024;
const EXPIRING = ["Gas certificate", "EICR", "EPC", "Insurance", "Warranty", "Tenancy", "Mortgage & finance"];
const MIME = ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "text/plain", "image/*"];

export default function DocumentForm() {
  const router = useRouter();
  const toast = useToast();
  const s = useStyles();
  const { colors } = useTheme();
  const [file, setFile] = useState<DocumentPicker.DocumentPickerAsset | null>(null);
  const [title, setTitle] = useState("");
  const [type, setType] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [expires, setExpires] = useState("");
  const expiresOk = !expires || /^\d{4}-\d{2}-\d{2}$/.test(expires.trim());

  const pick = async () => {
    tap();
    const r = await DocumentPicker.getDocumentAsync({ type: MIME, copyToCacheDirectory: true, multiple: false });
    if (r.canceled || !r.assets?.[0]) return;
    const a = r.assets[0];
    if (a.size && a.size > MAX) return toast("That file is over 20 MB", "error");
    setFile(a);
    if (!title) setTitle(a.name.replace(/\.[^.]+$/, ""));
  };

  const save = useMutation({
    mutationFn: () => uploadForm<DocItem>("/documents", { uri: file!.uri, name: file!.name, type: file!.mimeType ?? "application/octet-stream" }, { title, doc_type: type, notes, expires_on: expires.trim() }),
    onSuccess: () => { invalidate("documents"); toast("Document uploaded"); router.back(); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <FormScreen
      title="Upload document"
      testID="document-form-screen"
      footer={<Button title="Upload" icon="upload" disabled={!file || !type || !title.trim() || !expiresOk} loading={save.isPending} onPress={() => save.mutate()} testID="document-save-button" />}
    >
      <Pressable onPress={pick} style={[s.drop, file && { borderStyle: "solid", borderColor: colors.brand }]} testID="document-pick-button">
        <Icon name={file ? "file-check" : "file-up"} size={28} color={colors.brand} />
        <View style={{ flex: 1 }}>
          <Text style={s.dropTitle} numberOfLines={1}>{file ? file.name : "Choose a file"}</Text>
          <Text style={s.muted}>{file ? `${file.size ? fileSize(file.size) : ""}${file.size ? " · " : ""}Tap to change` : "PDF, Word, Excel, CSV, text or image · up to 20 MB"}</Text>
        </View>
      </Pressable>
      <Text style={s.label}>Document type</Text>
      <View style={s.chips}>
        {DOC_TYPES.map((t) => (
          <Chip key={t} label={t} selected={type === t} onPress={() => setType(t)} testID={`document-type-${t.replace(/\W+/g, "-").toLowerCase()}`} />
        ))}
      </View>
      <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Level 2 HomeBuyer survey" testID="document-title-input" />
      <Field
        label={EXPIRING.includes(type) ? "Expiry date (recommended)" : "Expiry date (optional)"}
        value={expires}
        onChangeText={setExpires}
        placeholder="YYYY-MM-DD"
        keyboardType="numbers-and-punctuation"
        testID="document-expiry-input"
      />
      {!expiresOk && <Text style={[s.muted, { color: colors.error }]}>Use the format YYYY-MM-DD, e.g. 2027-03-31</Text>}
      {EXPIRING.includes(type) && expiresOk && <Text style={s.muted}>We&apos;ll warn you on the dashboard 30 days before it expires.</Text>}
      <Field label="Notes (optional)" value={notes} onChangeText={setNotes} placeholder="e.g. Valid until March 2027" multiline testID="document-notes-input" />
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  drop: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.lg, borderRadius: radius.md, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.borderStrong, backgroundColor: c.surface, minHeight: 72 },
  dropTitle: { fontFamily: fonts.semibold, fontSize: 15, color: c.onSurface },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, marginTop: 2 },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceSecondary },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
}));
