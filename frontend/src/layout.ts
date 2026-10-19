import { useWindowDimensions } from "react-native";

/** Screen-size breakpoints for laying screens out in columns on tablets and desktop browsers. */
export const MAX_CONTENT = 1280;

export function useLayout() {
  const { width } = useWindowDimensions();
  return { wide: width >= 1024, tablet: width >= 768 };
}
