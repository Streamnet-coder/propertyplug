import { RentStatus } from "@/src/api";
import { ThemeColors } from "@/src/theme";

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthLabel = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;

export const EXPENSE_CATEGORIES = {
  repairs: "Repairs & maintenance",
  letting_agent: "Letting agent fees",
  insurance: "Insurance",
  mortgage: "Mortgage interest",
  service_charge: "Service charge / ground rent",
  utilities: "Utilities & council tax",
  other: "Other",
} as const;
export type ExpenseCategory = keyof typeof EXPENSE_CATEGORIES;

export const RENT_STATUS: Record<RentStatus, string> = { paid: "Paid", partial: "Part paid", late: "Late", due: "Due" };

export const rentTone = (st: RentStatus, c: ThemeColors) =>
  ({ paid: { bg: c.success, fg: c.onSuccess }, partial: { bg: c.orangeTint, fg: c.warning }, late: { bg: c.errorTint, fg: c.error }, due: { bg: c.surfaceTertiary, fg: c.muted } })[st];

export const today = () => new Date().toISOString().slice(0, 10);
