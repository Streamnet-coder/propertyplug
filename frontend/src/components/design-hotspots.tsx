import { Image } from "expo-image";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { fileUrl, gbp } from "@/src/api";
import { fonts, radius, space, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export type DesignPin = { i: number; x: number; y: number; name: string; spec: string; low: number; high: number; supplier: string };

/** AI-designed finished image with numbered dots on each material; tap a dot (or its row) for name, spec and cost. */
export function DesignHotspots({ path, pins }: { path: string; pins: DesignPin[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [ratio, setRatio] = useState(4 / 3);
  const [sel, setSel] = useState<number | null>(pins[0]?.i ?? null);
  const p = pins.find((x) => x.i === sel);

  return (
    <View style={{ gap: space.sm }} testID="design-hotspots">
      <View style={[s.frame, { aspectRatio: ratio }]}>
        <Image
          source={{ uri: fileUrl(path) }}
          style={{ width: "100%", height: "100%" }}
          contentFit="cover"
          transition={250}
          onLoad={(e) => e.source.width && e.source.height && setRatio(e.source.width / e.source.height)}
          testID="design-image"
        />
        {pins.map((pin, n) => (
          <Pressable
            key={pin.i}
            onPress={() => { tap(); setSel(pin.i); }}
            hitSlop={10}
            style={[s.dot, { left: `${pin.x}%`, top: `${pin.y}%`, backgroundColor: sel === pin.i ? colors.brandPrimary : colors.brand }]}
            testID={`design-pin-${pin.i}`}
          >
            <Text style={s.dotText}>{n + 1}</Text>
          </Pressable>
        ))}
        {p && (
          <View style={[s.tip, p.y > 60 ? { top: space.sm } : { bottom: space.sm }]} pointerEvents="none" testID="design-pin-tooltip">
            <Text style={s.tipName} numberOfLines={1}>{p.name}</Text>
            {p.spec ? <Text style={s.tipSpec} numberOfLines={1}>{p.spec}</Text> : null}
            <Text style={s.tipCost}>{gbp(p.low)} – {gbp(p.high)}</Text>
          </View>
        )}
      </View>
      {pins.length === 0 && <Text style={s.muted} testID="design-no-pins">Couldn&apos;t place price dots on this image. See the item list below.</Text>}
      {pins.map((pin, n) => (
        <Pressable key={pin.i} onPress={() => setSel(pin.i)} style={[s.row, sel === pin.i && { borderColor: colors.brandPrimary }]} testID={`design-pin-row-${pin.i}`}>
          <View style={[s.num, { backgroundColor: sel === pin.i ? colors.brandPrimary : colors.brand }]}><Text style={s.dotText}>{n + 1}</Text></View>
          <View style={{ flex: 1 }}>
            <Text style={s.rowName} numberOfLines={1}>{pin.name}</Text>
            <Text style={s.muted} numberOfLines={1}>{pin.supplier}</Text>
          </View>
          <Text style={s.rowCost}>{gbp(pin.low)}–{gbp(pin.high)}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const DOT = 28;
const useStyles = makeStyles((c) => ({
  frame: { width: "100%", borderRadius: radius.lg, overflow: "hidden", backgroundColor: c.surfaceTertiary },
  dot: { position: "absolute", width: DOT, height: DOT, marginLeft: -DOT / 2, marginTop: -DOT / 2, borderRadius: DOT / 2, borderWidth: 3, borderColor: "#FFFFFF", alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 4 },
  dotText: { fontFamily: fonts.bold, fontSize: 12, color: "#FFFFFF" },
  tip: { position: "absolute", left: space.sm, right: space.sm, backgroundColor: "rgba(15,23,42,0.85)", borderRadius: radius.md, paddingHorizontal: space.md, paddingVertical: space.sm, gap: 1 },
  tipName: { fontFamily: fonts.bold, fontSize: 14, color: "#FFFFFF" },
  tipSpec: { fontFamily: fonts.regular, fontSize: 12, color: "#E2E8F0" },
  tipCost: { fontFamily: fonts.extrabold, fontSize: 15, color: "#FDBA74", marginTop: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.sm, borderRadius: radius.md, borderWidth: 1.5, borderColor: c.border, backgroundColor: c.surface },
  num: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  rowName: { fontFamily: fonts.semibold, fontSize: 13, color: c.onSurface },
  rowCost: { fontFamily: fonts.bold, fontSize: 13, color: c.brand },
  muted: { fontFamily: fonts.regular, fontSize: 12, color: c.muted },
}));
