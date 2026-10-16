import { createElement } from "react";
import { View } from "react-native";

// react-native-webview has no web support, so the web preview renders the same Leaflet page in an iframe.
export function PortfolioMapView({ html }: { html: string }) {
  return (
    <View style={{ flex: 1 }} testID="portfolio-map-view">
      {createElement("iframe", { srcDoc: html, style: { border: 0, width: "100%", height: "100%" }, title: "Portfolio map" })}
    </View>
  );
}
