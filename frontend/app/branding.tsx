import { useMutation } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api, Branding, fileUrl } from "@/src/api";
import { PhotoPicker, PickedAsset } from "@/src/components/photo-picker";
import { Button, Field, fonts, FormScreen, Icon, radius, space } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { useBranding } from "@/src/queries";
import { makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { uploadAsset } from "@/src/upload";

const EMPTY: Branding = { company_name: "", contact_name: "", phone: "", email: "", website: "", tagline: "", logo_path: null };

export default function BrandingScreen() {
  const router = useRouter();
  const toast = useToast();
  const s = useStyles();
  const { colors } = useTheme();
  const { data } = useBranding();
  const [b, setB] = useState<Branding>(EMPTY);
  const [logo, setLogo] = useState<PickedAsset | null>(null);
  const set = (k: keyof Branding) => (v: string) => setB((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (data) setB({ ...EMPTY, ...data });
  }, [data]);

  const save = useMutation({
    mutationFn: async () => {
      const logo_path = logo ? await uploadAsset(logo) : b.logo_path ?? null;
      return api<Branding>("/branding", { method: "PUT", body: { ...b, logo_path } });
    },
    onSuccess: (d) => {
      queryClient.setQueryData(["branding"], d);
      toast("Branding saved. It now shows on every report & quote");
      router.back();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <FormScreen title="Report branding" testID="branding-screen" footer={<Button title="Save branding" loading={save.isPending} onPress={() => save.mutate()} testID="branding-save-button" />}>
      <Text style={s.muted}>Your logo and contact details appear at the top of PDF reports, live lender links and quote request pages.</Text>
      <View style={{ gap: space.sm }}>
        <Text style={s.label}>Company logo</Text>
        {b.logo_path && !logo ? (
          <View style={s.logoRow}>
            <Image source={{ uri: fileUrl(b.logo_path) }} style={s.logo} contentFit="contain" testID="branding-logo-current" />
            <View style={{ flex: 1, gap: space.sm }}>
              <Text style={s.muted}>Current logo</Text>
              <Pressable testID="branding-logo-remove" onPress={() => setB((x) => ({ ...x, logo_path: null }))} hitSlop={8}>
                <Text style={[s.muted, { color: colors.error, fontFamily: fonts.semibold }]}>Remove logo</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <PhotoPicker value={logo} onChange={setLogo} hint="Square PNG or JPG works best. We only ask for photo access when you tap." />
        )}
      </View>
      <Field label="Company name" value={b.company_name} onChangeText={set("company_name")} placeholder="e.g. Mapperley Property Co" testID="branding-company-input" />
      <Field label="Tagline" value={b.tagline} onChangeText={set("tagline")} placeholder="e.g. Nottingham refurbs & BRRR" testID="branding-tagline-input" />
      <Field label="Contact name" value={b.contact_name} onChangeText={set("contact_name")} placeholder="Your name" testID="branding-contact-input" />
      <View style={{ flexDirection: "row", gap: space.md }}>
        <View style={{ flex: 1 }}>
          <Field label="Phone" value={b.phone} onChangeText={set("phone")} keyboardType="phone-pad" placeholder="+44…" testID="branding-phone-input" />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="Website" value={b.website} onChangeText={set("website")} autoCapitalize="none" placeholder="yourco.co.uk" testID="branding-website-input" />
        </View>
      </View>
      <Field label="Email" value={b.email} onChangeText={set("email")} keyboardType="email-address" autoCapitalize="none" placeholder="hello@yourco.co.uk" testID="branding-email-input" />

      <Text style={s.label}>Preview</Text>
      <View style={s.preview} testID="branding-preview">
        {logo || b.logo_path ? (
          <Image source={{ uri: logo ? logo.uri : fileUrl(b.logo_path!) }} style={s.pLogo} contentFit="contain" />
        ) : (
          <View style={[s.pLogo, { alignItems: "center", justifyContent: "center" }]}><Icon name="building-2" size={22} color={colors.muted} /></View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={s.pName}>{b.company_name || "Your company"}</Text>
          {b.tagline ? <Text style={s.muted}>{b.tagline}</Text> : null}
          <Text style={[s.muted, { color: colors.brand }]} numberOfLines={2}>
            {[b.contact_name, b.phone, b.email, b.website].filter(Boolean).join(" · ") || "Contact details"}
          </Text>
        </View>
      </View>
    </FormScreen>
  );
}

const useStyles = makeStyles((c) => ({
  muted: { fontFamily: fonts.regular, fontSize: 13, color: c.muted, lineHeight: 18 },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurfaceTertiary },
  logoRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  logo: { width: 80, height: 80, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border },
  preview: { flexDirection: "row", gap: space.md, alignItems: "center", padding: space.md, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  pLogo: { width: 52, height: 52, borderRadius: radius.sm, backgroundColor: c.surfaceSecondary },
  pName: { fontFamily: fonts.extrabold, fontSize: 16, color: c.onSurface },
}));
