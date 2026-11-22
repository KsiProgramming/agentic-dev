import { BotIcon, SparklesIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type ProviderName = "claude" | "copilot";

export const PROVIDER_NAMES: Record<ProviderName, string> = {
  claude: "Claude",
  copilot: "Copilot",
};

/** The provider an agent ran on and its model (8.3): an icon and plain text, the model in the
 * mono font. Colour means status only, so a provider is never a coloured pill. */
export function ProviderLabel({
  provider,
  model,
  className,
}: {
  provider: ProviderName;
  model?: string | null;
  className?: string;
}) {
  const Icon = provider === "copilot" ? BotIcon : SparklesIcon;
  return (
    <span
      data-testid="step-provider"
      data-provider={provider}
      className={cn("inline-flex min-w-0 items-center gap-1", className)}
    >
      <Icon aria-hidden="true" className="size-3 shrink-0" />
      <span className="shrink-0">{PROVIDER_NAMES[provider]}</span>
      {model ? (
        <>
          <span aria-hidden="true">·</span>
          <span data-testid="step-model" className="min-w-0 truncate font-mono">
            {model}
          </span>
        </>
      ) : null}
    </span>
  );
}
