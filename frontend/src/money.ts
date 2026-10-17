import { useAuth } from "@/src/auth";

/** False when the signed-in person has tasks-only (no money) access to the open shared project. */
export function useCanSeeMoney() {
  const { user } = useAuth();
  return user?.acting_as?.money !== false;
}
