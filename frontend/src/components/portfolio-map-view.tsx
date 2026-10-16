import { View } from "react-native";
import { WebView } from "react-native-webview";

export function PortfolioMapView({ html }: { html: string }) {
  return (
    <View style={{ flex: 1 }} testID="portfolio-map-view">
      <WebView originWhitelist={["*"]} source={{ html }} style={{ flex: 1 }} />
    </View>
  );
}
