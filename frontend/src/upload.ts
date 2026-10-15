import type { PickedAsset } from "@/src/components/photo-picker";
import { uploadForm } from "@/src/utils/upload";

export async function uploadAsset(a: PickedAsset): Promise<string> {
  const res = await uploadForm<{ path: string }>("/upload", { uri: a.uri, name: a.name, type: a.type });
  return res.path;
}
