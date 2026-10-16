import { PlanningApp } from "@/src/api";

export const DECISIONS: Record<PlanningApp["decision"], string> = { pending: "Pending", approved: "Approved", refused: "Refused", withdrawn: "Withdrawn" };

export function decisionDue(a: PlanningApp) {
  const d = a.days_to_decision;
  if (d == null) return null;
  return d < 0 ? `Decision overdue by ${-d} day${d === -1 ? "" : "s"}` : d === 0 ? "Decision due today" : `Decision due in ${d} day${d === 1 ? "" : "s"}`;
}
