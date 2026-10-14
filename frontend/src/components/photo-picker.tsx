import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import React, { useState } from "react";
import { Linking, Platform, Pressable, Text, View } from "react-native";

import { Button, fonts, Icon, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export type PickedAsset = { uri: string; name: string; type: string };

async function ensurePermission(source: "camera" | "library"): Promise<"granted" | "denied" | "blocked"> {
  const get = source === "camera" ? ImagePicker.getCameraPermissionsAsync : ImagePicker.getMediaLibraryPermissionsAsync;
  const req = source === "camera" ? ImagePicker.requestCameraPermissionsAsync : ImagePicker.requestMediaLibraryPermissionsAsync;
  const cur = await get();
  if (cur.granted) return "granted";
  if (!cur.canAskAgain) return "blocked";
  const res = await req();
  if (res.granted) return "granted";
  return res.canAskAgain ? "denied" : "blocked";
}

export function PhotoPicker({ value, onChange, hint }: { value: PickedAsset | null; onChange: (a: PickedAsset | null) => void; hint: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [perm, setPerm] = useState<{ source: "camera" | "library"; state: "denied" | "blocked" } | null>(null);

  const pick = async (source: "camera" | "library") => {
    if (Platform.OS !== "web") {
      const st = await ensurePermission(source);
      if (st !== "granted") {
        setPerm({ source, state: st });
        return;
      }
    }
    setPerm(null);
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.6, allowsEditing: false };
    const res = source === "camera" ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled || !res.assets?.[0]) return;
    const a = res.assets[0];
    const name = a.fileName || `photo-${Date.now()}.jpg`;
    onChange({ uri: a.uri, name: name.includes(".") ? name : `${name}.jpg`, type: a.mimeType || "image/jpeg" });
  };

  return (
    <View style={s.wrap}>
      {value ? (
        <View>
          <Image source={{ uri: value.uri }} style={s.preview} contentFit="cover" testID="photo-preview" />
          <Pressable testID="photo-remove-button" onPress={() => onChange(null)} style={s.remove}>
            <Icon name="x" size={16} color={colors.onSurfaceInverse} />
          </Pressable>
        </View>
      ) : (
        <View style={s.drop}>
          <Icon name="camera" size={26} color={colors.brand} />
          <Text style={s.hint}>{hint}</Text>
          <View style={s.row}>
            <Button small variant="secondary" icon="camera" title="Take photo" onPress={() => pick("camera")} testID="photo-camera-button" style={{ flex: 1 }} />
            <Button small variant="outline" icon="image" title="Gallery" onPress={() => pick("library")} testID="photo-gallery-button" style={{ flex: 1 }} />
          </View>
        </View>
      )}
      {perm && (
        <View style={s.permBox} testID="photo-permission-banner">
          <Text style={s.permText}>
            {perm.source === "camera" ? "Camera" : "Photo library"} access is needed to attach site photos.
            {perm.state === "blocked" ? " Enable it in Settings." : " Tap again to allow."}
          </Text>
          {perm.state === "blocked" && (
            <Button small variant="outline" title="Open Settings" icon="settings" onPress={() => Linking.openSettings()} testID="open-settings-button" />
          )}
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  wrap: { gap: space.sm },
  drop: {
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: c.borderStrong,
    borderRadius: radius.lg,
    padding: space.lg,
    alignItems: "center",
    gap: space.sm,
    backgroundColor: c.surfaceSecondary,
  },
  hint: { fontFamily: fonts.medium, fontSize: 13, color: c.muted, textAlign: "center" },
  row: { flexDirection: "row", gap: space.sm, alignSelf: "stretch", marginTop: space.xs },
  preview: { width: "100%", height: 200, borderRadius: radius.lg, backgroundColor: c.surfaceTertiary },
  remove: {
    position: "absolute",
    top: space.sm,
    right: space.sm,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: c.scrim,
    alignItems: "center",
    justifyContent: "center",
  },
  permBox: { backgroundColor: c.orangeTint, borderRadius: radius.md, padding: space.md, gap: space.sm },
  permText: { fontFamily: fonts.medium, fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 18 },
}));
