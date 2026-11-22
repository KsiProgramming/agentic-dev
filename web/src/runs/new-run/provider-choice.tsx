"use client";

import { BotIcon, FolderGit2Icon } from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import type { GithubUserConnections } from "@/api/queries";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { FieldMessage } from "@/forms/schema-form/schema-fields";

import type { RunAgent, RunProvider } from "./providers";

export type { RunProvider };

const PROVIDER_NAME: Record<RunProvider, string> = { claude: "Claude", copilot: "Copilot" };

/** What the run can be given, from the personal GitHub connections: the ones that work, and when
 * none do, one sentence on why. */
export function copilotOptions(
  data: GithubUserConnections | undefined,
  failed: boolean,
): { usable: GithubUserConnections["connections"]; reason: string | null } {
  if (failed) return { usable: [], reason: "Could not load your GitHub accounts." };
  if (!data) return { usable: [], reason: "Checking your GitHub accounts…" };
  const usable = data.connections.filter((c) => c.status === "connected");
  if (usable.length > 0) return { usable, reason: null };
  if (!data.configured) {
    return { usable, reason: "Personal GitHub accounts are not set up on this server." };
  }
  if (data.connections.length > 0) {
    return { usable, reason: "Your GitHub account needs attention before it can run Copilot." };
  }
  return { usable, reason: "Connect your GitHub account to run on your Copilot." };
}

/** The first choice of the run form: Claude (default) or GitHub Copilot. Copilot needs a
 * connected personal GitHub account; with several, the person picks whose Copilot the run uses. */
export function ProviderChoice({
  provider,
  connectionId,
  onChange,
  accounts,
  failed,
  error,
  disabled,
  needsCopilot = false,
  pinned = [],
}: {
  provider: RunProvider;
  connectionId: string;
  onChange: (provider: RunProvider, connectionId: string) => void;
  accounts: GithubUserConnections | undefined;
  failed: boolean;
  error?: string;
  disabled: boolean;
  /** Some agent runs on Copilot (its own provider, or the choice), so an account is needed. */
  needsCopilot?: boolean;
  /** Agents whose own provider keeps them off the choice (8.3). */
  pinned?: RunAgent[];
}) {
  const name = useId();
  const selectId = useId();
  const { usable, reason } = copilotOptions(accounts, failed);
  const copilotOff = usable.length === 0;
  const chosen = usable.find((c) => c.id === connectionId) ?? usable[0];
  return (
    <fieldset
      className="flex flex-col gap-2"
      aria-describedby={error ? `${name}-error` : `${name}-help`}
    >
      <legend className="mb-2 text-meta font-medium">Provider</legend>
      <label className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 hover:bg-muted has-checked:border-primary has-checked:bg-surface-subtle">
        <input
          type="radio"
          name={name}
          value="claude"
          checked={provider === "claude"}
          disabled={disabled}
          onChange={() => onChange("claude", chosen?.id ?? "")}
          className="size-4"
        />
        <BotIcon aria-hidden="true" className="size-4" />
        <span className="flex-1 font-medium">Claude</span>
      </label>
      <label
        className={
          copilotOff
            ? "flex items-center gap-3 rounded-lg border px-3 py-2.5 text-placeholder"
            : "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 hover:bg-muted has-checked:border-primary has-checked:bg-surface-subtle"
        }
      >
        <input
          type="radio"
          name={name}
          value="copilot"
          checked={provider === "copilot" && !copilotOff}
          disabled={disabled || copilotOff}
          onChange={() => onChange("copilot", (chosen ?? usable[0])!.id)}
          className="size-4"
        />
        <FolderGit2Icon aria-hidden="true" className="size-4" />
        <span className="flex flex-1 flex-col">
          <span className="font-medium">GitHub Copilot</span>
          {copilotOff && reason ? <span className="text-caption">{reason}</span> : null}
        </span>
      </label>
      {(provider === "copilot" || needsCopilot) && !copilotOff ? (
        usable.length > 1 ? (
          <Field>
            <FieldLabel htmlFor={selectId}>Run as</FieldLabel>
            <NativeSelect
              id={selectId}
              className="font-mono"
              value={chosen?.id ?? ""}
              disabled={disabled}
              onChange={(e) => onChange("copilot", e.target.value)}
            >
              {usable.map((c) => (
                <NativeSelectOption key={c.id} value={c.id}>
                  {c.login}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
        ) : null
      ) : null}
      {pinned.length > 0 ? (
        <ul className="flex flex-col gap-0.5 text-caption text-foreground-secondary">
          {pinned.map((a) => (
            <li key={a.id}>
              <span className="font-mono">{a.id}</span> stays on {PROVIDER_NAME[a.provider]}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <FieldMessage id={`${name}-error`}>{error}</FieldMessage>
      ) : (provider === "copilot" || needsCopilot) && chosen ? (
        <FieldDescription id={`${name}-help`}>
          {provider === "copilot" ? "Runs" : "Its Copilot steps run"} on{" "}
          <span className="font-mono">{chosen.login}</span>&apos;s Copilot. Cost is the list price
          of its AI credits.
        </FieldDescription>
      ) : copilotOff ? (
        <FieldDescription id={`${name}-help`}>
          Copilot runs on a person&apos;s own GitHub account.{" "}
          <Link href="/settings/integrations" className="text-foreground underline">
            Integrations
          </Link>
        </FieldDescription>
      ) : (
        <FieldDescription id={`${name}-help`}>
          Claude is the default. Pick Copilot to run on a GitHub account&apos;s subscription.
        </FieldDescription>
      )}
    </fieldset>
  );
}
