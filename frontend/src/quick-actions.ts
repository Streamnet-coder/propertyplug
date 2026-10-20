import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { IconName } from "@/src/components/ui";
import { useCanSeeMoney } from "@/src/money";
import { useProject } from "@/src/queries";

export type QuickAction = { id: string; icon: IconName; label: string; onPress: () => void; pro?: boolean };

/** Project shortcuts shown as the Home grid on phones and the left sidebar on desktop. */
export function useQuickActions() {
  const router = useRouter();
  const money = useCanSeeMoney();
  const { user } = useAuth();
  const { data: p } = useProject();
  const all: QuickAction[] = [
    { id: "ai", icon: "sparkles", label: "AI cost", onPress: () => router.push("/ai-estimate") },
    { id: "brrr", icon: "calculator", label: "BRRR", onPress: () => router.push("/brrr"), pro: true },
    { id: "sold", icon: "map-pinned", label: "Sold prices", onPress: () => router.push("/sold-map") },
    { id: "epc", icon: "leaf", label: "EPC plan", onPress: () => router.push("/epc") },
    { id: "report", icon: "share-2", label: "Share", onPress: () => router.push("/share-report") },
    { id: "receipt", icon: "receipt", label: "Receipt", onPress: () => router.push("/receipt-form") },
    { id: "snags", icon: "list-checks", label: "Snags", onPress: () => router.push("/snags") },
    { id: "inbox", icon: "inbox", label: "My tasks", onPress: () => router.push("/inbox") },
  ];
  const actions = all.filter((a) => !(a.id === "brrr" && (p?.property_type === "land" || p?.purpose === "personal"))
    && (money || !["ai", "brrr", "report", "receipt", "sold", "epc"].includes(a.id)));
  return { actions, isPro: user?.plan === "pro" };
}
