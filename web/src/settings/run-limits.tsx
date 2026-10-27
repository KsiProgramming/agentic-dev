"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { GaugeIcon, LoaderCircleIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, validationIssues } from "@/api/errors";
import {
  usePolicy,
  useSavePolicy,
  type RunLimitOverrides,
  type RunLimits,
  type WorkspacePolicy,
} from "@/api/queries";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { budgetSchema, parseBudget } from "@/runs/budget";
import { useWorkspaceId } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";

const PURPOSE =
  "What one run may use. A run that goes over a limit stops with the reason. Lower a limit to tighten it; a run keeps the limits it started with.";

type CountKey = Exclude<keyof RunLimits, "wall_time_s" | "approval_ttl_s" | "budget_usd">;

const COUNT_FIELDS = [
  { key: "agents_alive", label: "Agents at once", help: "Agents running at the same time." },
  { key: "agents_spawned", label: "Agents per run", help: "Agents a run may start in all." },
  { key: "loop_iterations", label: "Loop iterations", help: "The most rounds a loop may run." },
  { key: "max_depth", label: "Nesting depth", help: "How deep loops and maps may nest." },
] as const satisfies readonly { key: CountKey; label: string; help: string }[];

/** "" keeps the platform's limit; otherwise a whole number from 1 to `max`. */
function count(max: number) {
  return z
    .string()
    .trim()
    .refine((v) => v === "" || /^\d+$/.test(v), "A whole number, like 3.")
    .refine((v) => v === "" || (Number(v) >= 1 && Number(v) <= max), `From 1 to ${max}.`);
}

function schemaFor(defaults: RunLimits) {
  const minutes = z
    .string()
    .trim()
    .refine((v) => v === "" || /^\d+$/.test(v), "Whole minutes, like 30.");
  return z
    .object({
      agents_alive: count(defaults.agents_alive),
      agents_spawned: count(defaults.agents_spawned),
      loop_iterations: count(defaults.loop_iterations),
      max_depth: count(defaults.max_depth),
      wall_time_hours: minutes,
      wall_time_minutes: minutes,
      approval_ttl_hours: z
        .string()
        .trim()
        .refine((v) => v === "" || /^\d+(\.\d{1,2})?$/.test(v), "Hours, like 24 or 0.5.")
        .refine(
          (v) => v === "" || (ttlSeconds(v)! >= 60 && ttlSeconds(v)! <= defaults.approval_ttl_s),
          `From 1 minute to ${duration(defaults.approval_ttl_s)}.`,
        ),
      budget_usd: budgetSchema(),
    })
    .superRefine((v, ctx) => {
      const seconds = wallTimeSeconds(v.wall_time_hours, v.wall_time_minutes);
      if (seconds === null) return;
      if (seconds < 60 || seconds > defaults.wall_time_s) {
        ctx.addIssue({
          code: "custom",
          path: ["wall_time_hours"],
          message: `From 1 minute to ${duration(defaults.wall_time_s)}.`,
        });
      }
    });
}

type Values = z.infer<ReturnType<typeof schemaFor>>;

/** Seconds from the hours and minutes fields; null when both are empty (the platform's). */
function wallTimeSeconds(hours: string, minutes: string): number | null {
  if (hours.trim() === "" && minutes.trim() === "") return null;
  return (Number(hours || 0) * 60 + Number(minutes || 0)) * 60;
}

/** Seconds from the approval time to live in hours; null when empty (the platform's). */
function ttlSeconds(hours: string): number | null {
  return hours.trim() === "" ? null : Math.round(Number(hours) * 3600);
}

/** `7200` → "2 h", `5400` → "1 h 30 min", `90` → "1 min 30 s". */
export function duration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts = [h ? `${h} h` : "", m ? `${m} min` : "", s ? `${s} s` : ""].filter(Boolean);
  return parts.length ? parts.join(" ") : "0 s";
}

function valuesOf(overrides: RunLimitOverrides): Values {
  const wall = overrides.wall_time_s;
  return {
    agents_alive: overrides.agents_alive?.toString() ?? "",
    agents_spawned: overrides.agents_spawned?.toString() ?? "",
    loop_iterations: overrides.loop_iterations?.toString() ?? "",
    max_depth: overrides.max_depth?.toString() ?? "",
    wall_time_hours: wall == null ? "" : String(Math.floor(wall / 3600)),
    wall_time_minutes: wall == null ? "" : String(Math.floor((wall % 3600) / 60)),
    approval_ttl_hours:
      overrides.approval_ttl_s == null
        ? ""
        : String(Math.round((overrides.approval_ttl_s / 3600) * 100) / 100),
    budget_usd: overrides.budget_usd?.toString() ?? "",
  };
}

function overridesOf(values: Values): RunLimitOverrides {
  const number = (v: string) => (v.trim() === "" ? null : Number(v));
  return {
    agents_alive: number(values.agents_alive),
    agents_spawned: number(values.agents_spawned),
    loop_iterations: number(values.loop_iterations),
    max_depth: number(values.max_depth),
    wall_time_s: wallTimeSeconds(values.wall_time_hours, values.wall_time_minutes),
    approval_ttl_s: ttlSeconds(values.approval_ttl_hours),
    budget_usd: parseBudget(values.budget_usd),
  };
}

/** The "Run limits" card: the platform's limits, and the workspace's lower ones. */
export function RunLimitsCard({
  baseUrl,
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const policy = usePolicy({ workspaceId, baseUrl });

  const card = (children: ReactNode) => (
    <ConnectionCard icon={GaugeIcon} title="Run limits" purpose={PURPOSE} testId="limits-card">
      {children}
    </ConnectionCard>
  );

  if (policy.isPending) return card(<LoadingState rows={3} label="Loading the run limits…" />);
  if (policy.isError) {
    return card(
      <ErrorState message={policy.error.message} onRetry={() => void policy.refetch()} />,
    );
  }
  return card(
    // Remounted when the stored limits change, so the fields show what was saved.
    <LimitsForm
      key={JSON.stringify(policy.data.overrides)}
      policy={policy.data}
      workspaceId={workspaceId}
      baseUrl={baseUrl}
    />,
  );
}

function LimitsForm({
  policy,
  workspaceId,
  baseUrl,
}: {
  policy: WorkspacePolicy;
  workspaceId: string;
  baseUrl?: string;
}) {
  const save = useSavePolicy({ workspaceId, baseUrl });
  const { defaults, overrides } = policy;
  const form = useForm<Values>({
    resolver: zodResolver(schemaFor(defaults)),
    defaultValues: valuesOf(overrides),
  });
  const errors = form.formState.errors;
  const pending = form.formState.isSubmitting || save.isPending;
  const lowered = Object.values(overrides).some((v) => v != null);

  async function onSubmit(values: Values) {
    try {
      await save.mutateAsync(overridesOf(values));
      toast.success("Run limits saved. New runs get them.");
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 422) return; // Shown below.
      // A 422 names the field: `["body", "<limit>"]`.
      for (const issue of validationIssues(err.body)) {
        const field = issue.loc.at(-1);
        if (field === "wall_time_s") form.setError("wall_time_hours", { message: issue.msg });
        if (field === "approval_ttl_s") {
          form.setError("approval_ttl_hours", { message: issue.msg });
        }
        if (field === "budget_usd") form.setError("budget_usd", { message: issue.msg });
        const known = COUNT_FIELDS.find((f) => f.key === field);
        if (known) form.setError(known.key, { message: issue.msg });
      }
    }
  }

  const formError =
    save.error && !(save.error instanceof ApiError && save.error.status === 422)
      ? save.error.message
      : null;

  return (
    <form
      onSubmit={(e) => void form.handleSubmit(onSubmit)(e)}
      className="flex flex-col gap-4"
      noValidate
      aria-label="Run limits"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {COUNT_FIELDS.map((f) => (
          <LimitInput
            key={f.key}
            label={f.label}
            help={`${f.help} Platform limit: ${defaults[f.key]}.`}
            placeholder={String(defaults[f.key])}
            error={errors[f.key]?.message}
            registration={form.register(f.key)}
            disabled={pending}
          />
        ))}
      </div>
      <WallTimeInput
        platform={defaults.wall_time_s}
        error={errors.wall_time_hours?.message ?? errors.wall_time_minutes?.message}
        hours={form.register("wall_time_hours")}
        minutes={form.register("wall_time_minutes")}
        disabled={pending}
      />
      <LimitInput
        label="Approval time to live (hours)"
        help={`How long a gate waits for a decision; then the run is cancelled as "Expired". A gate may set a shorter time. Platform limit: ${duration(defaults.approval_ttl_s)}.`}
        placeholder={String(defaults.approval_ttl_s / 3600)}
        inputMode="decimal"
        error={errors.approval_ttl_hours?.message}
        registration={form.register("approval_ttl_hours")}
        disabled={pending}
      />
      <LimitInput
        label="Budget (USD)"
        help="The most a run may spend; it stops once its cost reaches this. Empty: no budget, and runs are not capped. A run may set its own when it starts."
        placeholder="No budget"
        inputMode="decimal"
        error={errors.budget_usd?.message}
        registration={form.register("budget_usd")}
        disabled={pending}
      />
      {formError ? (
        <Alert variant="destructive">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending}>
          {form.formState.isSubmitting ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : null}
          {form.formState.isSubmitting ? "Saving…" : "Save limits"}
        </Button>
        {lowered ? (
          <ConfirmButton
            label="Reset to defaults"
            title="Reset the run limits?"
            description="New runs get the platform's limits again, and no budget. Runs already started keep theirs."
            confirmLabel="Reset limits"
            disabled={pending}
            onConfirm={() =>
              save.mutate(
                {},
                { onSuccess: () => toast.success("Run limits reset to the platform's.") },
              )
            }
          />
        ) : null}
      </div>
    </form>
  );
}

function LimitInput({
  label,
  help,
  placeholder,
  inputMode = "numeric",
  error,
  registration,
  disabled,
}: {
  label: string;
  help: string;
  placeholder: string;
  inputMode?: "numeric" | "decimal";
  error: string | undefined;
  registration: UseFormRegisterReturn;
  disabled: boolean;
}) {
  const id = useId();
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        inputMode={inputMode}
        autoComplete="off"
        placeholder={placeholder}
        className="tabular-nums"
        aria-invalid={error ? true : undefined}
        aria-describedby={[`${id}-help`, error ? `${id}-error` : null].filter(Boolean).join(" ")}
        disabled={disabled}
        {...registration}
      />
      <FieldDescription id={`${id}-help`}>{help}</FieldDescription>
      {error ? <FieldMessage id={`${id}-error`}>{error}</FieldMessage> : null}
    </Field>
  );
}

function WallTimeInput({
  platform,
  error,
  hours,
  minutes,
  disabled,
}: {
  platform: number;
  error: string | undefined;
  hours: UseFormRegisterReturn;
  minutes: UseFormRegisterReturn;
  disabled: boolean;
}) {
  const id = useId();
  const described = [`${id}-help`, error ? `${id}-error` : null].filter(Boolean).join(" ");
  return (
    <fieldset className="flex flex-col gap-2" data-invalid={error ? true : undefined}>
      <legend className="mb-2 text-sm font-medium">Wall time</legend>
      <div className="flex items-center gap-2">
        <Input
          aria-label="Wall time hours"
          inputMode="numeric"
          autoComplete="off"
          placeholder={String(Math.floor(platform / 3600))}
          className="w-20 tabular-nums"
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          disabled={disabled}
          {...hours}
        />
        <span className="text-sm text-muted-foreground">h</span>
        <Input
          aria-label="Wall time minutes"
          inputMode="numeric"
          autoComplete="off"
          placeholder={String(Math.floor((platform % 3600) / 60))}
          className="w-20 tabular-nums"
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          disabled={disabled}
          {...minutes}
        />
        <span className="text-sm text-muted-foreground">min</span>
      </div>
      <FieldDescription id={`${id}-help`}>
        Time a run may spend executing; time waiting for an approval does not count. Platform limit:{" "}
        {duration(platform)}.
      </FieldDescription>
      {error ? <FieldMessage id={`${id}-error`}>{error}</FieldMessage> : null}
    </fieldset>
  );
}
