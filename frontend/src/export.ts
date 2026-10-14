import { Directory, File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { BACKEND_URL, getApiToken } from "@/src/api";

/** Download all account data as a ZIP of CSV spreadsheets. */
export async function downloadDataExport() {
  const url = `${BACKEND_URL}/api/export`;
  const headers = { Authorization: `Bearer ${getApiToken() ?? ""}` };
  const name = `builder-assist-export-${new Date().toISOString().slice(0, 10)}.zip`;
  if (Platform.OS === "web") {
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error("Export failed. Please try again");
    const href = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
    URL.revokeObjectURL(href);
    return;
  }
  const file = await File.downloadFileAsync(url, new File(new Directory(Paths.cache), name), { headers, idempotent: true });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(file.uri, { mimeType: "application/zip", dialogTitle: "Save your Builder Assist data" });
  }
}
