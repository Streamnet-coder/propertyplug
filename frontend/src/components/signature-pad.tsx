import { useRef, useState } from "react";
import { PanResponder, Pressable, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { fonts, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export type SignatureValue = { path: string; width: number; height: number };
const HEIGHT = 160;
const r = (n: number) => Math.round(n * 10) / 10;

/** Finger/mouse signature pad. Produces an SVG path (vector, tiny) instead of an image. */
export function SignaturePad({ onChange, testID }: { onChange: (v: SignatureValue | null) => void; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [d, setD] = useState("");
  const width = useRef(300);
  const acc = useRef("");

  const emit = (path: string) => onChange(path.split("L").length > 2 ? { path, width: width.current, height: HEIGHT } : null);
  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: (e) => {
        acc.current += `${acc.current ? " " : ""}M${r(e.nativeEvent.locationX)} ${r(e.nativeEvent.locationY)}`;
        setD(acc.current);
      },
      onPanResponderMove: (e) => {
        acc.current += ` L${r(e.nativeEvent.locationX)} ${r(e.nativeEvent.locationY)}`;
        setD(acc.current);
      },
      onPanResponderRelease: () => emit(acc.current),
    }),
  ).current;

  const clear = () => {
    acc.current = "";
    setD("");
    onChange(null);
  };

  return (
    <View style={{ gap: space.xs }}>
      <View style={s.pad} onLayout={(e) => (width.current = r(e.nativeEvent.layout.width))} {...pan.panHandlers} testID={testID}>
        <Svg width="100%" height={HEIGHT} pointerEvents="none">
          <Path d={d} stroke={colors.onSurface} strokeWidth={2.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </Svg>
        {!d && <Text style={s.hint} pointerEvents="none">Sign here with your finger</Text>}
      </View>
      <Pressable onPress={clear} hitSlop={8} style={{ alignSelf: "flex-end", minHeight: 32, justifyContent: "center" }} testID={`${testID}-clear`}>
        <Text style={s.clear}>Clear</Text>
      </Pressable>
    </View>
  );
}

/** Read-only render of a stored signature. */
export function SignatureView({ sig, height = 56 }: { sig: SignatureValue; height?: number }) {
  const { colors } = useTheme();
  return (
    <Svg width={(sig.width / sig.height) * height} height={height} viewBox={`0 0 ${sig.width} ${sig.height}`}>
      <Path d={sig.path} stroke={colors.onSurface} strokeWidth={2.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

const useStyles = makeStyles((c) => ({
  pad: { height: HEIGHT, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.borderStrong, borderRadius: 12, backgroundColor: c.surface, overflow: "hidden", justifyContent: "center" },
  hint: { position: "absolute", alignSelf: "center", fontFamily: fonts.regular, fontSize: 13, color: c.muted },
  clear: { fontFamily: fonts.semibold, fontSize: 13, color: c.brand },
}));
