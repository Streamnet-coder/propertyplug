import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { IconName } from "@/src/components/ui";
import { useCanSeeMoney } from "@/src/money";
import { useProject } from "@/src/queries";

export type ToolGroup = "Research" | "Analyse" | "Manage";
export const GROUPS: ToolGroup[] = ["Research", "Analyse", "Manage"];
export const GROUP_ICONS: Record<ToolGroup, IconName> = { Research: "search", Analyse: "chart-column", Manage: "clipboard-list" };
export type QuickAction = { id: string; icon: IconName; label: string; onPress: () => void; pro?: boolean; group: ToolGroup };

/** Project shortcuts shown as the Home grid on phones and the left sidebar on desktop. */
export function useQuickActions() {
  const router = useRouter();
  const money = useCanSeeMoney();
  const { user } = useAuth();
  const { data: p } = useProject();
  const all: QuickAction[] = [
    { id: "sold", icon: "map-pinned", label: "Sold prices", onPress: () => router.push("/sold-map"), group: "Research" },
    { id: "rent", icon: "house", label: "Rent comps", onPress: () => router.push("/rent-comps"), group: "Research" },
    { id: "epc", icon: "leaf", label: "EPC plan", onPress: () => router.push("/epc"), group: "Research" },
    { id: "ai", icon: "sparkles", label: "AI cost", onPress: () => router.push("/ai-estimate"), group: "Analyse" },
    { id: "brrr", icon: "calculator", label: "BRRR", onPress: () => router.push("/brrr"), pro: true, group: "Analyse" },
    { id: "report", icon: "share-2", label: "Share", onPress: () => router.push("/share-report"), group: "Manage" },
    { id: "receipt", icon: "receipt", label: "Receipt", onPress: () => router.push("/receipt-form"), group: "Manage" },
    { id: "snags", icon: "list-checks", label: "Snags", onPress: () => router.push("/snags"), group: "Manage" },
    { id: "inbox", icon: "inbox", label: "My tasks", onPress: () => router.push("/inbox"), group: "Manage" },
  ];
  const actions = all.filter((a) => !(a.id === "brrr" && (p?.property_type === "land" || p?.purpose === "personal"))
    && (money || !["ai", "brrr", "report", "receipt", "sold", "epc", "rent"].includes(a.id)));
  return { actions, isPro: user?.plan === "pro" };
}
