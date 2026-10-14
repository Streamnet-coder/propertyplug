import { Platform } from "react-native";

import { api } from "@/src/api";
import type { PickedAsset } from "@/src/components/photo-picker";

export async function uploadAsset(a: PickedAsset): Promise<string> {
  const form = new FormData();
  if (Platform.OS === "web") {
    const blob = await (await fetch(a.uri)).blob();
    form.append("file", blob, a.name);
  } else {
    form.append("file", { uri: a.uri, name: a.name, type: a.type } as any);
  }
  const res = await api<{ path: string }>("/upload", { method: "POST", form });
  return res.path;
}
