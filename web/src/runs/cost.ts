import type { components } from "@/api/schema";
import { numberFormat } from "@/lib/locale";

type RunUsage = components["schemas"]["RunUsage"];

/** Tokens and estimated cost, added up over usage events. */
export interface TokenUsage {
  /** Uncached input. Events logged before cost tracking count cache tokens here too. */
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  /** The cost of the priced usage; a lower bound when `costComplete` is false. */
  estimatedUsd: number;
  /** False once some usage had no price. */
  costComplete: boolean;
  /** The models of the usage that had no price, for saying why the cost is missing. */
  unpricedModels: string[];
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** The usage of one `usage` event's payload. */
export function usageOfEvent(payload: Record<string, unknown>): TokenUsage {
  const usd = payload.estimated_usd;
  const priced = typeof usd === "number" && Number.isFinite(usd);
  const model = typeof payload.model === "string" ? payload.model : null;
  return {
    inputTokens: count(payload.input_tokens),
    outputTokens: count(payload.output_tokens),
    cacheReadTokens: count(payload.cache_read_tokens),
    cacheWriteTokens: count(payload.cache_write_tokens),
    estimatedUsd: priced ? usd : 0,
    costComplete: priced,
    unpricedModels: priced || model === null ? [] : [model],
  };
}

/** A run's usage totals from its summary. */
export function usageOfRun(usage: RunUsage): TokenUsage {
  return {
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    cacheReadTokens: usage.cache_read_tokens,
    cacheWriteTokens: usage.cache_write_tokens,
    estimatedUsd: usage.estimated_usd,
    costComplete: usage.cost_complete,
    unpricedModels: [],
  };
}

export function addUsage(a: TokenUsage | null, b: TokenUsage | null): TokenUsage | null {
  if (a === null) return b;
  if (b === null) return a;
  return {
    inputTokens: a.inputTokens + b.inputTokens,
    outputTokens: a.outputTokens + b.outputTokens,
    cacheReadTokens: a.cacheReadTokens + b.cacheReadTokens,
    cacheWriteTokens: a.cacheWriteTokens + b.cacheWriteTokens,
    estimatedUsd: a.estimatedUsd + b.estimatedUsd,
    costComplete: a.costComplete && b.costComplete,
    unpricedModels: [...new Set([...a.unpricedModels, ...b.unpricedModels])],
  };
}

// "$", not "US$": every amount here is USD.
const dollars = () =>
  numberFormat({
    style: "currency",
    currency: "USD",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const cents = () =>
  numberFormat({
    style: "currency",
    currency: "USD",
    currencyDisplay: "narrowSymbol",
    maximumSignificantDigits: 3,
  });
const prices = () =>
  numberFormat({
    style: "currency",
    currency: "USD",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });

/** USD for people: agent turns cost fractions of a cent, so small amounts keep 3 significant
 * digits ("$0.0423") and tiny ones say so ("<$0.001"). */
export function formatUsd(usd: number): string {
  if (usd === 0) return dollars().format(0);
  if (usd < 0.001) return `<${cents().format(0.001)}`;
  return usd < 1 ? cents().format(usd) : dollars().format(usd);
}

/** A list price or a limit in USD, to the cent and up to 4 decimals ("$3.00", "$0.075"). */
export function formatPrice(usd: number): string {
  return prices().format(usd);
}

/** The cost to show: "—" when nothing was priced, "≥ $x" when only part of it was. */
export function formatCost(usage: TokenUsage): string {
  if (usage.costComplete) return formatUsd(usage.estimatedUsd);
  return usage.estimatedUsd > 0 ? `≥ ${formatUsd(usage.estimatedUsd)}` : "—";
}

/** Why the cost is missing or partial, or `null` when it is complete. */
export function costCaveat(usage: TokenUsage): string | null {
  if (usage.costComplete) return null;
  const models = usage.unpricedModels;
  return models.length > 0
    ? `No price for ${models.join(", ")}: add one in Settings → Model pricing.`
    : "Some usage was logged before costs were tracked.";
}

/** A token count in a few characters ("12.3K"). */
export function formatTokens(n: number): string {
  return numberFormat({ notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** A share from 0 to 1 as a whole percentage ("67%"). */
export function formatPercent(share: number): string {
  return numberFormat({ style: "percent", maximumFractionDigits: 0 }).format(share);
}

/** A count in full ("12,345"). */
export function formatCount(n: number): string {
  return numberFormat().format(n);
}

/** Every count in full, for a tooltip. */
export function usageDetails(usage: TokenUsage): string {
  return [
    `${formatCount(usage.inputTokens)} input`,
    `${formatCount(usage.outputTokens)} output`,
    `${formatCount(usage.cacheReadTokens)} cache read`,
    `${formatCount(usage.cacheWriteTokens)} cache write tokens`,
  ].join(" · ");
}
