import { LinearGradient } from "expo-linear-gradient";
import { Text, View } from "react-native";

import { fonts, Icon } from "@/src/components/ui";
import { useTheme } from "@/src/theme";

export function BrandMark({ size = 40 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <LinearGradient
      colors={[colors.brand, colors.accent]}
      start={{ x: 0, y: 1 }}
      end={{ x: 1, y: 0 }}
      style={{ width: size, height: size, borderRadius: size * 0.3, alignItems: "center", justifyContent: "center" }}
    >
      <Icon name="house-plug" size={size * 0.55} color={colors.onBrand} />
    </LinearGradient>
  );
}

export function BrandLogo() {
  const { colors } = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
      <BrandMark size={38} />
      <View>
        <Text style={{ fontFamily: "Inter-ExtraBoldItalic", fontSize: 19, color: colors.onSurface, letterSpacing: -0.4 }} testID="brand-wordmark">
          Property<Text style={{ color: colors.brandPrimary }}>Plug</Text>
        </Text>
        <Text style={{ fontFamily: fonts.medium, fontStyle: "italic", fontSize: 10, color: colors.muted, letterSpacing: 0.3 }} testID="brand-tagline">All landlord needs</Text>
      </View>
    </View>
  );
}
