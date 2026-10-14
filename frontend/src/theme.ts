// Design tokens for Builder Assist (light theme). Keys match the "color" block of /app/design_guidelines.json.
import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#ffffff",
  onSurface: "#0f172a",
  surfaceSecondary: "#f8fafc",
  onSurfaceSecondary: "#1e293b",
  surfaceTertiary: "#f1f5f9",
  onSurfaceTertiary: "#334155",
  surfaceInverse: "#1e293b",
  onSurfaceInverse: "#f8fafc",
  muted: "#64748b",

  brand: "#0f766e",
  onBrand: "#ffffff",
  brandPrimary: "#f97316",
  onBrandPrimary: "#ffffff",
  brandPrimaryPressed: "#ea580c",
  brandSecondary: "#0f766e",
  onBrandSecondary: "#ffffff",
  brandTertiary: "#f0fdf4",
  onBrandTertiary: "#0f766e",
  accent: "#06b6d4",
  orangeTint: "#fff7ed",
  orangeBorder: "#fed7aa",
  heroEnd: "#ecfeff",
  errorTint: "#fef2f2",

  success: "#10b981",
  onSuccess: "#ffffff",
  warning: "#ea580c",
  onWarning: "#ffffff",
  error: "#ef4444",
  onError: "#ffffff",
  info: "#06b6d4",
  onInfo: "#ffffff",

  border: "#e2e8f0",
  borderStrong: "#cbd5e1",
  divider: "#f1f5f9",
  scrim: "rgba(15,23,42,0.82)",
  overlay: "rgba(15,23,42,0.5)",
};

export type ThemeColors = typeof light;

export const defaultScheme = "light" satisfies ColorScheme;

export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

export const colors = light;

export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

setColorScheme?.(themes.dark ? null : defaultScheme);

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const sys = system as ColorScheme | null;
  const scheme: ColorScheme = sys && themes[sys] ? sys : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

export function makeStyles<T extends StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>>(
  factory: (colors: ThemeColors) => T & StyleSheet.NamedStyles<any>,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}
