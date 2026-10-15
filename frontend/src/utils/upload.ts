import { fetch as expoFetch } from "expo/fetch";
import { Platform } from "react-native";

import { api } from "@/src/api";

export type UploadFile = { uri: string; name: string; type: string };

/**
 * Multipart upload that works on web AND real phones.
 * Native global fetch is expo/fetch, which rejects RN-style `{ uri, name, type }` parts, so read the file into a Blob first.
 */
export async function uploadForm<T>(path: string, file: UploadFile, fields: Record<string, string> = {}): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  const blob = Platform.OS === "web" ? await (await fetch(file.uri)).blob() : await (await expoFetch(file.uri)).blob();
  form.append("file", blob, file.name);
  return api<T>(path, { method: "POST", form });
}
