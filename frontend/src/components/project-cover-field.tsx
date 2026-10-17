import { Image } from "expo-image";
import { Pressable, Text, View } from "react-native";

import { fileUrl } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { fonts, radius, space, tap } from "@/src/components/ui";
import { api } from "@/src/api";
import { uploadAsset } from "@/src/upload";
import { makeStyles, useTheme } from "@/src/theme";

export type CoverChoice = { asset: PickedAsset | null; removed: boolean };

/** Save the picked/removed cover on the (now active) project. No-op when nothing changed. */
export async function saveCover(c: CoverChoice) {
  if (c.asset) await api("/project/cover", { method: "PUT", body: { storage_path: await uploadAsset(c.asset) } });
  else if (c.removed) await api("/project/cover", { method: "PUT", body: { storage_path: null } });
}

/** Preferred project image picker for the project form: shows the current cover with Change / Remove. */
export function ProjectCoverField({ current, value, onChange }: { current: string | null | undefined; value: CoverChoice; onChange: (c: CoverChoice) => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  const showing = value.asset ? value.asset.uri : !value.removed && current ? fileUrl(current) : null;

  return (
    <View style={{ gap: space.sm }} testID="project-cover-field">
      <Text style={s.label}>Project photo</Text>
      {showing ? (
        <View style={{ gap: space.sm }}>
          <Image source={{ uri: showing }} style={s.img} contentFit="cover" testID="project-cover-preview" />
          <View style={{ flexDirection: "row", gap: space.lg }}>
            <Pressable onPress={() => { tap(); onChange({ asset: null, removed: true }); }} hitSlop={8} testID="project-cover-remove">
              <Text style={[s.link, { color: colors.error }]}>Remove photo</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <PhotoPicker value={null} onChange={(a) => onChange({ asset: a, removed: false })} hint="Pick a photo you'll recognise, like the front of the house. It shows on your project list." />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  img: { width: "100%", height: 160, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  link: { fontFamily: fonts.semibold, fontSize: 13, minHeight: 44, textAlignVertical: "center" },
}));
