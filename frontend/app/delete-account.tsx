import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Platform, Text, View } from "react-native";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Button, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { downloadDataExport } from "@/src/export";
import { shareBudgetPdf, shareLenderPack, shareProgressReport, shareSnagPdf } from "@/src/report";
import { useToast } from "@/src/toast";

const WHAT = ["All projects, budgets, line items and receipts", "Photos, milestones, snags and shopping lists", "Quotes, payment schedules and share links", "Your profile, branding and referral history"];

const confirmDelete = () =>
  Platform.OS === "web"
    ? Promise.resolve(globalThis.confirm("This permanently deletes your account and all data. Continue?"))
    : new Promise<boolean>((resolve) =>
        Alert.alert("Delete account?", "This permanently deletes everything and cannot be undone.", [
          { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
          { text: "Delete", style: "destructive", onPress: () => resolve(true) },
        ]),
      );

export default function DeleteAccount() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { signOut } = useAuth();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<void>, done?: string) => {
    setExporting(key);
    try {
      await fn();
      if (done) toast(done);
    } catch (e: any) {
      toast(e?.message ?? "Export failed", "error");
    } finally {
      setExporting(null);
    }
  };

  const submit = async () => {
    setError("");
    if (!(await confirmDelete())) return;
    setBusy(true);
    try {
      await api("/auth/account", { method: "DELETE", body: { password } });
      await signOut();
      toast("Your account has been deleted", "info");
      router.replace("/welcome");
    } catch (e: any) {
      setError(e?.message ?? "Account deletion failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <FormScreen
      title="Delete account"
      testID="delete-account-screen"
      footer={<Button variant="danger" icon="trash-2" title="Permanently delete account" disabled={!password} loading={busy} onPress={submit} testID="delete-account-confirm" />}
    >
      <View style={s.warn}>
        <Icon name="triangle-alert" size={22} color={colors.error} />
        <Text style={s.warnText}>This can&apos;t be undone. Your account and everything in it will be permanently deleted straight away.</Text>
      </View>
      <View style={{ gap: space.sm }}>
        <Text style={s.label}>What gets deleted</Text>
        {WHAT.map((w) => (
          <View key={w} style={{ flexDirection: "row", gap: space.sm, alignItems: "center" }}>
            <Icon name="x" size={14} color={colors.error} />
            <Text style={s.body}>{w}</Text>
          </View>
        ))}
        <Text style={s.muted}>Live links you&apos;ve shared with lenders, trades or partners will stop working.</Text>
      </View>
      <View style={s.export} testID="data-export-section">
        <Text style={s.label}>Download your data first</Text>
        <Text style={s.muted}>Spreadsheets (CSV) for every data type in one ZIP, plus PDF reports for your active project.</Text>
        <Button small icon="download" title="Download all data (ZIP)" loading={exporting === "zip"} onPress={() => run("zip", downloadDataExport, "Data export ready")} testID="export-data-button" />
        <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
          <Button small variant="outline" icon="file-down" title="Progress" loading={exporting === "progress"} onPress={() => run("progress", shareProgressReport)} testID="export-progress-pdf" />
          <Button small variant="outline" icon="file-down" title="Budget" loading={exporting === "budget"} onPress={() => run("budget", shareBudgetPdf)} testID="export-budget-pdf" />
          <Button small variant="outline" icon="file-down" title="Snags" loading={exporting === "snags"} onPress={() => run("snags", shareSnagPdf)} testID="export-snags-pdf" />
          <Button small variant="outline" icon="file-down" title="Lender pack" loading={exporting === "pack"} onPress={() => run("pack", () => shareLenderPack(false))} testID="export-pack-pdf" />
        </View>
      </View>
      <Field label="Enter your password to confirm" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" autoComplete="password" testID="delete-account-password" />
      {!!error && <Text style={s.error} testID="delete-account-error" accessibilityRole="alert">{error}</Text>}
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  warn: { flexDirection: "row", gap: space.md, alignItems: "flex-start", backgroundColor: c.errorTint, borderRadius: radius.md, padding: space.lg },
  warnText: { flex: 1, fontFamily: fonts.semibold, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  label: { fontFamily: fonts.bold, fontSize: 15, color: c.onSurface },
  body: { fontFamily: fonts.regular, fontSize: 14, color: c.onSurfaceSecondary },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted, marginTop: space.xs },
  export: { gap: space.sm, padding: space.lg, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  error: { fontFamily: fonts.semibold, fontSize: 13, color: c.error },
}));
