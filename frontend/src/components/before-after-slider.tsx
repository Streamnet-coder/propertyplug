import { Image } from "expo-image";
import { useMemo, useRef, useState } from "react";
import { PanResponder, Text, View } from "react-native";

import { fonts, Icon, radius, space } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const clamp = (n: number) => Math.min(1, Math.max(0, n));

/** Drag the handle left/right to wipe between a before photo (left) and an after photo (right). */
export function BeforeAfterSlider({ before, after, height = 300, testID = "before-after-slider" }: { before?: string; after?: string; height?: number; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [w, setW] = useState(0);
  const [pos, setPos] = useState(0.5);
  const posRef = useRef(0.5);
  const start = useRef(0.5);
  const wRef = useRef(0);
  const move = (p: number) => { posRef.current = p; setPos(p); };

  const pan = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: () => { start.current = posRef.current; },
        onPanResponderMove: (_, g) => wRef.current && move(clamp(start.current + g.dx / wRef.current)),
      }),
    [],
  );

  return (
    <View
      testID={testID}
      style={[s.wrap, { height }]}
      onLayout={(e) => { wRef.current = e.nativeEvent.layout.width; setW(e.nativeEvent.layout.width); }}
      {...pan.panHandlers}
    >
      <Image source={{ uri: after }} style={{ width: "100%", height }} contentFit="cover" transition={150} />
      <View style={[s.clip, { width: w * pos, height }]} pointerEvents="none">
        <Image source={{ uri: before }} style={{ width: w, height }} contentFit="cover" transition={150} />
      </View>
      <View style={[s.tag, { left: space.sm }]} pointerEvents="none"><Text style={s.tagText}>BEFORE</Text></View>
      <View style={[s.tag, s.tagAfter, { right: space.sm }]} pointerEvents="none"><Text style={s.tagText}>AFTER</Text></View>
      <View style={[s.line, { left: w * pos - 1.5 }]} pointerEvents="none" />
      <View style={[s.handle, { left: w * pos - 22, top: height / 2 - 22 }]} pointerEvents="none" testID={`${testID}-handle`}>
        <Icon name="chevrons-left-right" size={20} color={colors.brand} />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  wrap: { width: "100%", borderRadius: radius.lg, overflow: "hidden", backgroundColor: c.surfaceTertiary },
  clip: { position: "absolute", left: 0, top: 0, overflow: "hidden" },
  line: { position: "absolute", top: 0, bottom: 0, width: 3, backgroundColor: c.surface },
  handle: {
    position: "absolute", width: 44, height: 44, borderRadius: 22, backgroundColor: c.surface, alignItems: "center", justifyContent: "center",
    shadowColor: c.onSurface, shadowOpacity: 0.25, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 4,
  },
  tag: { position: "absolute", top: space.sm, backgroundColor: c.surfaceInverse, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  tagAfter: { backgroundColor: c.success },
  tagText: { fontFamily: fonts.bold, fontSize: 10, color: c.onSurfaceInverse, letterSpacing: 0.6 },
}));
