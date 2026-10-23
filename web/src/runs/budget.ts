import { z } from "zod";

/** The budget range the API accepts (`BUDGET_MIN_USD`, `BUDGET_MAX_USD`). */
export const BUDGET_MIN_USD = 0.01;
export const BUDGET_MAX_USD = 1_000_000;

/** A budget field: "" leaves it unset; otherwise dollars, like 5 or 2.50. */
export function budgetSchema() {
  return z
    .string()
    .trim()
    .refine((v) => v === "" || /^\$?\d+(\.\d+)?$/.test(v), "An amount in dollars, like 5 or 2.50.")
    .refine((v) => {
      const usd = parseBudget(v);
      return usd === null || (usd >= BUDGET_MIN_USD && usd <= BUDGET_MAX_USD);
    }, "From $0.01 to $1,000,000.");
}

/** The amount in a budget field, or null when it is empty. */
export function parseBudget(text: string): number | null {
  const v = text.trim().replace(/^\$/, "");
  return v === "" ? null : Number(v);
}

/** Whether a run refusal (`errors` of a `policy_limits` detail) is about the budget. */
export function isBudgetError(error: string): boolean {
  return error.includes("budget cannot be enforced");
}
