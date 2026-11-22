"use client";

import { LoaderCircleIcon, ServerCogIcon } from "lucide-react";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { ApiError, validationIssues } from "@/api/errors";
import { Money } from "@/components/display";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { useWorkspaceId } from "@/workspace";

import { ConnectionCard } from "./connection-card";
import {
  useProviderSettings,
  useSaveProviderSettings,
  type ProviderSettings,
} from "./provider-settings-api";

const PURPOSE =
  "Where a run's agents run when the run, the workflow and the step name no provider, and what Copilot usage costs. A run keeps the providers it was created with.";

const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/;
const CREDIT = /^\d+(\.\d{1,6})?$/;

const CHOICES = [
  { value: "claude", label: "Claude" },
  { value: "copilot", label: "GitHub Copilot" },
] as const;

type Draft = { provider: string; model: string; credit: string };
type Errors = { model?: string; credit?: string };

function draftOf(s: ProviderSettings): Draft {
  return {
    provider: s.default_provider,
    model: s.copilot_model ?? "",
    credit: String(s.copilot_credit_usd),
  };
}

/** The "Default provider" card (8.3): the workspace's default provider, the model a Copilot
 * agent with none of its own runs on, and the price of a Copilot AI credit. */
export function ProviderSettingsCard({
  baseUrl,
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const settings = useProviderSettings({ workspaceId, baseUrl });
  const card = (children: ReactNode) => (
    <ConnectionCard
      icon={ServerCogIcon}
      title="Default provider"
      purpose={PURPOSE}
      testId="provider-settings-card"
    >
      {children}
    </ConnectionCard>
  );
  if (settings.isPending) return card(<LoadingState rows={3} label="Loading the settings…" />);
  if (settings.isError) {
    return card(
      <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />,
    );
  }
  return card(
    <ProviderForm
      key={JSON.stringify(settings.data)}
      saved={settings.data}
      workspaceId={workspaceId}
      baseUrl={baseUrl}
    />,
  );
}

function ProviderForm({
  saved,
  workspaceId,
  baseUrl,
}: {
  saved: ProviderSettings;
  workspaceId: string;
  baseUrl?: string;
}) {
  const save = useSaveProviderSettings({ workspaceId, baseUrl });
  const groupId = useId();
  const modelId = useId();
  const creditId = useId();
  const initial = draftOf(saved);
  const [draft, setDraft] = useState<Draft>(initial);
  const [errors, setErrors] = useState<Errors>({});
  const dirty =
    draft.provider !== initial.provider ||
    draft.model !== initial.model ||
    draft.credit !== initial.credit;
  const isDefaultCredit = Number(draft.credit) === saved.default_copilot_credit_usd;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    const model = draft.model.trim();
    const credit = draft.credit.trim();
    if (model && !MODEL_ID.test(model)) {
      found.model = "Letters, digits and . _ : @ / - only, no spaces.";
    }
    if (!CREDIT.test(credit) || Number(credit) <= 0 || Number(credit) > 100) {
      found.credit = "A price above 0 and up to 100, with up to 6 decimals, like 0.01.";
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    try {
      await save.mutateAsync({
        default_provider: draft.provider as ProviderSettings["default_provider"],
        copilot_model: model || null,
        copilot_credit_usd:
          Number(credit) === saved.default_copilot_credit_usd ? null : Number(credit),
      });
      toast.success("Provider settings saved.");
    } catch (err) {
      if (err instanceof ApiError) {
        const on: Errors = {};
        for (const issue of validationIssues(err.body)) {
          const field = issue.loc.at(-1);
          if (field === "copilot_model") on.model = issue.msg;
          if (field === "copilot_credit_usd") on.credit = issue.msg;
        }
        setErrors(on);
      }
    }
  }

  const pending = save.isPending;
  const refusal = save.error && Object.keys(errors).length === 0 ? save.error.message : null;
  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      noValidate
      className="flex flex-col gap-5"
      data-testid="provider-settings-form"
    >
      <fieldset className="flex flex-col gap-2" aria-describedby={`${groupId}-help`}>
        <legend className="mb-2 text-meta font-medium">Default provider</legend>
        <div className="flex flex-wrap gap-2">
          {CHOICES.map((c) => (
            <label
              key={c.value}
              className="flex flex-1 cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 hover:bg-muted has-checked:border-primary has-checked:bg-surface-subtle has-focus-visible:ring-2 has-focus-visible:ring-ring sm:flex-none"
            >
              <input
                type="radio"
                name={groupId}
                value={c.value}
                checked={draft.provider === c.value}
                disabled={pending}
                onChange={() => setDraft({ ...draft, provider: c.value })}
                className="size-4"
              />
              <span className="font-medium">{c.label}</span>
            </label>
          ))}
        </div>
        <FieldDescription id={`${groupId}-help`}>
          Copilot runs on the personal GitHub connection of the person who starts the run. Runs a
          trigger starts stay on Claude.
        </FieldDescription>
      </fieldset>
      <Field data-invalid={errors.model ? true : undefined}>
        <FieldLabel htmlFor={modelId}>Copilot model (optional)</FieldLabel>
        <Input
          id={modelId}
          value={draft.model}
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
          placeholder="auto"
          disabled={pending}
          aria-invalid={errors.model ? true : undefined}
          aria-describedby={errors.model ? `${modelId}-error` : `${modelId}-help`}
          onChange={(e) => setDraft({ ...draft, model: e.target.value })}
        />
        {errors.model ? (
          <FieldMessage id={`${modelId}-error`}>{errors.model}</FieldMessage>
        ) : (
          <FieldDescription id={`${modelId}-help`}>
            The model a Copilot agent with no model of its own runs on. Empty: the worker&apos;s own
            (auto lets Copilot choose). Model names are per person, so none is checked.
          </FieldDescription>
        )}
      </Field>
      <Field data-invalid={errors.credit ? true : undefined}>
        <FieldLabel htmlFor={creditId}>Copilot AI credit (USD)</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            id={creditId}
            inputMode="decimal"
            value={draft.credit}
            autoComplete="off"
            className="w-32"
            disabled={pending}
            aria-invalid={errors.credit ? true : undefined}
            aria-describedby={errors.credit ? `${creditId}-error` : `${creditId}-help`}
            onChange={(e) => setDraft({ ...draft, credit: e.target.value })}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pending || isDefaultCredit}
            onClick={() => setDraft({ ...draft, credit: String(saved.default_copilot_credit_usd) })}
          >
            Reset to GitHub&apos;s price
          </Button>
        </div>
        {errors.credit ? (
          <FieldMessage id={`${creditId}-error`}>{errors.credit}</FieldMessage>
        ) : (
          <FieldDescription id={`${creditId}-help`}>
            GitHub bills <Money usd={saved.default_copilot_credit_usd} kind="price" /> per AI
            credit. A Copilot step&apos;s cost is its credits at this price: the list price, not
            what a plan with included credits charged.
          </FieldDescription>
        )}
      </Field>
      {refusal ? (
        <Alert variant="destructive">
          <AlertDescription>{refusal}</AlertDescription>
        </Alert>
      ) : null}
      {dirty ? (
        <div
          data-testid="provider-save-bar"
          className="sticky bottom-4 z-10 flex flex-wrap items-center gap-2 rounded-lg border bg-background p-3 shadow-dock"
        >
          <p role="status" className="mr-auto font-medium">
            Unsaved changes
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => {
              setDraft(initial);
              setErrors({});
              save.reset();
            }}
          >
            Discard
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? (
              <LoaderCircleIcon
                aria-hidden="true"
                data-icon="inline-start"
                className="motion-safe:animate-spin"
              />
            ) : null}
            {pending ? "Saving…" : "Save settings"}
          </Button>
        </div>
      ) : null}
    </form>
  );
}
