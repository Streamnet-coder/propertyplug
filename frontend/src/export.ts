import { Directory, File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { BACKEND_URL, getApiToken } from "@/src/api";

/** Download an authenticated backend file; on web save it, on native open the share/save sheet. */
export async function downloadFile(apiPath: string, name: string, mimeType: string, dialogTitle: string) {
  const url = `${BACKEND_URL}/api${apiPath}`;
  const headers = { Authorization: `Bearer ${getApiToken() ?? ""}` };
  if (Platform.OS === "web") {
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error("Download failed. Please try again");
    const href = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
    URL.revokeObjectURL(href);
    return;
  }
  const safe = name.replace(/[^\w.\- ]+/g, "_");
  const file = await File.downloadFileAsync(url, new File(new Directory(Paths.cache), safe), { headers, idempotent: true });
  if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(file.uri, { mimeType, dialogTitle });
}

/** Download all account data as a ZIP of CSV spreadsheets. */
export const downloadDataExport = () =>
  downloadFile("/export", `builder-assist-export-${new Date().toISOString().slice(0, 10)}.zip`, "application/zip", "Save your Builder Assist data");
