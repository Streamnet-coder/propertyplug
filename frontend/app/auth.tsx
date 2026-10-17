import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { BrandLogo } from "@/src/components/brand";
import { Button, fonts, Field, Icon, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function AuthScreen() {
  const params = useLocalSearchParams<{ mode?: string; next?: string }>();
  const [mode, setMode] = useState<"login" | "register">(params.mode === "login" ? "login" : "register");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const s = useStyles();
  const { colors } = useTheme();
  const isReg = mode === "register";

  const submit = async () => {
    setError("");
    if (!email || !password || (isReg && !name)) {
      setError("Please fill in all fields");
      return;
    }
    setBusy(true);
    try {
      if (isReg) await signUp(name, email, password);
      else await signIn(email, password);
      // Only follow in-app paths (e.g. an invite link) so `next` can't send people off-site.
      if (params.next?.startsWith("/join/")) router.replace(params.next as any);
      else router.replace("/(tabs)");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.root}>
      <KeyboardAwareScrollView
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingTop: insets.top + space.md, paddingBottom: insets.bottom + space.xl, paddingHorizontal: space.xl }}
      >
        <Pressable testID="auth-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/welcome"))} style={s.back} hitSlop={10}>
          <Icon name="arrow-left" size={22} />
        </Pressable>
        <View style={{ marginTop: space.xl, gap: space.sm }}>
          <BrandLogo />
          <Text style={s.title}>{isReg ? "Start your free trial" : "Welcome back"}</Text>
          <Text style={s.sub}>{isReg ? "30 days free. Your first project is pre-loaded so you can explore instantly." : "Sign in to manage your developments."}</Text>
        </View>
        <View style={{ gap: space.lg, marginTop: space.xl }}>
          {isReg && <Field label="Full name" value={name} onChangeText={setName} placeholder="John Doe" testID="auth-name-input" autoComplete="name" />}
          <Field
            label="Email"
            value={email}
            onChangeText={setEmail}
            placeholder="you@example.co.uk"
            autoCapitalize="none"
            keyboardType="email-address"
            autoComplete="email"
            testID="auth-email-input"
          />
          <Field
            label="Password"
            value={password}
            onChangeText={setPassword}
            placeholder="At least 6 characters"
            secureTextEntry
            testID="auth-password-input"
            onSubmitEditing={submit}
          />
          {error ? (
            <View style={s.error} testID="auth-error">
              <Icon name="circle-alert" size={16} color={colors.error} />
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}
          <Button title={isReg ? "Create account" : "Sign in"} onPress={submit} loading={busy} testID="auth-submit-button" />
          <Pressable testID="auth-switch-mode" onPress={() => { setMode(isReg ? "login" : "register"); setError(""); }} style={{ alignItems: "center", padding: space.sm }}>
            <Text style={s.switch}>
              {isReg ? "Already have an account? " : "New here? "}
              <Text style={{ color: colors.brand, fontFamily: fonts.bold }}>{isReg ? "Sign in" : "Start free trial"}</Text>
            </Text>
          </Pressable>
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.extrabold, fontSize: 28, color: c.onSurface, marginTop: space.md, letterSpacing: -0.5 },
  sub: { fontFamily: fonts.regular, fontSize: 15, color: c.muted, lineHeight: 22 },
  error: { flexDirection: "row", gap: 8, alignItems: "center", backgroundColor: c.errorTint, padding: space.md, borderRadius: 12 },
  errorText: { fontFamily: fonts.medium, fontSize: 13, color: c.error, flex: 1 },
  switch: { fontFamily: fonts.regular, fontSize: 14, color: c.muted },
}));
