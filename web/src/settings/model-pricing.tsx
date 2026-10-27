"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircleIcon, PlusIcon, ReceiptIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, validationIssues } from "@/api/errors";
import {
  usePricing,
  useSavePricing,
  type ModelPricing,
  type Price,
  type PriceOverride,
} from "@/api/queries";
import { Money, TokenCount } from "@/components/display";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { useWorkspaceId } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";

const PURPOSE =
  "USD per million tokens. A run is priced when its usage is logged, so a change applies to new usage only.";

const PRICE_FIELDS = [
  { key: "input", label: "Input" },
  { key: "output", label: "Output" },
  { key: "cache_write_5m", label: "Cache write (5 min)" },
  { key: "cache_write_1h", label: "Cache write (1 h)" },
  { key: "cache_read", label: "Cache read" },
] as const satisfies readonly { key: keyof Price; label: string }[];

const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/;

const price = z
  .string()
  .trim()
  .min(1, "Enter a price.")
  .refine((v) => /^\d+(\.\d{1,4})?$/.test(v), "A number with up to 4 decimals, like 2.5.")
  .refine((v) => Number(v) <= 100_000, "At most 100,000.");

const schema = z.object({
  model: z.string().trim().regex(MODEL_ID, "Letters, digits and . _ : @ / - only, no spaces."),
  input: price,
  output: price,
  cache_write_5m: price,
  cache_write_1h: price,
  cache_read: price,
});

type Values = z.infer<typeof schema>;

/** The prices a model is priced with: the workspace's, else the list price. */
function effective(model: ModelPricing): Price | null {
  return model.override ?? model.default;
}

/** Every override but `model`'s, which `next` replaces (or removes, when null). */
function overridesWith(models: ModelPricing[], model: string, next: Price | null): PriceOverride[] {
  const kept = models
    .filter((m) => m.model !== model && m.override)
    .map((m) => ({ model: m.model, price: m.override! }));
  return next ? [...kept, { model, price: next }] : kept;
}

/** The "Model pricing" card: list prices, and the workspace's own prices on top. */
export function ModelPricingCard({
  baseUrl,
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const pricing = usePricing({ workspaceId, baseUrl });
  const save = useSavePricing({ workspaceId, baseUrl });
  // The model being edited; "" for a new one.
  const [editing, setEditing] = useState<string | null>(null);

  const card = (children: ReactNode) => (
    <ConnectionCard
      icon={ReceiptIcon}
      title="Model pricing"
      purpose={PURPOSE}
      testId="pricing-card"
    >
      {children}
    </ConnectionCard>
  );

  if (pricing.isPending) return card(<LoadingState rows={3} label="Loading the prices…" />);
  if (pricing.isError) {
    return card(
      <ErrorState message={pricing.error.message} onRetry={() => void pricing.refetch()} />,
    );
  }

  const { models, as_of: asOf } = pricing.data;
  const custom = models.filter((m) => m.override).length;
  const reset = (model: string) =>
    save.mutate(overridesWith(models, model, null), {
      onSuccess: () => toast.success(`${model} is back to its list price.`),
    });

  return card(
    <>
      <div className="overflow-x-auto rounded-md border">
        <Table aria-label="Model prices, USD per million tokens" className="text-meta">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Model</TableHead>
              {PRICE_FIELDS.map((f) => (
                <TableHead key={f.key} className="text-right">
                  {f.label}
                </TableHead>
              ))}
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => {
              const prices = effective(model);
              return (
                <TableRow key={model.model} data-model={model.model}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-xs">{model.model}</span>
                      {model.override ? (
                        <Badge variant="secondary" className="h-5 px-1.5 text-xs">
                          Custom
                        </Badge>
                      ) : null}
                    </span>
                    {model.long_context && !model.override ? (
                      <span className="block text-xs text-muted-foreground">
                        Higher price above{" "}
                        <TokenCount value={model.long_context.above_tokens} focusable={false} />{" "}
                        prompt tokens
                      </span>
                    ) : null}
                  </TableCell>
                  {PRICE_FIELDS.map((f) => (
                    <TableCell key={f.key} className="text-right tabular-nums">
                      {prices ? <Money usd={prices[f.key]} kind="price" /> : "—"}
                    </TableCell>
                  ))}
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        type="button"
                        size="xs"
                        variant="ghost"
                        onClick={() => setEditing(model.model)}
                      >
                        Edit<span className="sr-only"> {model.model}</span>
                      </Button>
                      {model.override ? (
                        <ConfirmButton
                          label="Reset"
                          title={`Reset ${model.model}?`}
                          description={
                            model.default
                              ? "New usage is priced at the list price again. Past runs keep their cost."
                              : "This model has no list price: its new usage will have no cost."
                          }
                          confirmLabel="Reset price"
                          disabled={save.isPending}
                          onConfirm={() => reset(model.model)}
                        />
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" onClick={() => setEditing("")}>
          <PlusIcon aria-hidden="true" data-icon="inline-start" />
          Add model
        </Button>
        {custom > 0 ? (
          <ConfirmButton
            label="Reset all"
            title="Reset every model to its list price?"
            description="Your prices are removed. Past runs keep their cost."
            confirmLabel="Reset all"
            disabled={save.isPending}
            onConfirm={() =>
              save.mutate([], { onSuccess: () => toast.success("Prices reset to list prices.") })
            }
          />
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          List prices as of <time dateTime={asOf}>{asOf}</time>
        </span>
      </div>
      {save.isError && editing === null ? (
        <Alert variant="destructive">
          <AlertDescription>{save.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {editing !== null ? (
        <PriceDialog
          models={models}
          model={models.find((m) => m.model === editing) ?? null}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </>,
  );
}

function PriceInput({
  label,
  error,
  registration,
  disabled,
}: {
  label: string;
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
        inputMode="decimal"
        autoComplete="off"
        className="tabular-nums"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        disabled={disabled}
        {...registration}
      />
      {error ? <FieldMessage id={`${id}-error`}>{error}</FieldMessage> : null}
    </Field>
  );
}

/** Sets one model's price; `model` is null for a model that is not listed yet. */
function PriceDialog({
  models,
  model,
  workspaceId,
  baseUrl,
  onClose,
}: {
  models: ModelPricing[];
  model: ModelPricing | null;
  workspaceId: string;
  baseUrl?: string;
  onClose: () => void;
}) {
  const modelId = useId();
  const save = useSavePricing({ workspaceId, baseUrl });
  const start = model ? effective(model) : null;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      model: model?.model ?? "",
      ...Object.fromEntries(PRICE_FIELDS.map((f) => [f.key, start ? String(start[f.key]) : ""])),
    },
  });
  const errors = form.formState.errors;
  const pending = form.formState.isSubmitting;

  async function onSubmit(values: Values) {
    const name = values.model;
    if (!model && models.some((m) => m.model === name)) {
      form.setError("model", { message: "This model is listed already: edit it there." });
      return;
    }
    const next = Object.fromEntries(PRICE_FIELDS.map((f) => [f.key, Number(values[f.key])]));
    try {
      await save.mutateAsync(overridesWith(models, name, next as Price));
      toast.success(`Price for ${name} saved.`);
      onClose();
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 422) return; // Shown below.
      // A 422 names the field: `["body", "overrides", i, "price", "<field>"]`.
      for (const issue of validationIssues(err.body)) {
        const field = issue.loc.at(-1);
        const key =
          PRICE_FIELDS.find((f) => f.key === field)?.key ?? (field === "model" ? "model" : null);
        if (key) form.setError(key, { message: issue.msg });
      }
    }
  }

  const formError =
    save.error && !(save.error instanceof ApiError && save.error.status === 422)
      ? save.error.message
      : null;

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{model ? `Price for ${model.model}` : "Add a model"}</DialogTitle>
          <DialogDescription>
            USD per million tokens. New usage is priced with it; past runs keep their cost.
          </DialogDescription>
        </DialogHeader>
        <form
          id="price-form"
          onSubmit={(e) => void form.handleSubmit(onSubmit)(e)}
          className="flex flex-col gap-4"
          noValidate
        >
          {model ? null : (
            <Field data-invalid={errors.model ? true : undefined}>
              <FieldLabel htmlFor={modelId}>Model id</FieldLabel>
              <Input
                id={modelId}
                autoComplete="off"
                placeholder="claude-opus-5-5"
                className="font-mono"
                aria-invalid={errors.model ? true : undefined}
                aria-describedby={[`${modelId}-help`, errors.model ? `${modelId}-error` : null]
                  .filter(Boolean)
                  .join(" ")}
                disabled={pending}
                {...form.register("model")}
              />
              <FieldDescription id={`${modelId}-help`}>
                The id the provider reports in its usage, e.g. a proxy or fine-tuned model.
              </FieldDescription>
              {errors.model?.message ? (
                <FieldMessage id={`${modelId}-error`}>{errors.model.message}</FieldMessage>
              ) : null}
            </Field>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {PRICE_FIELDS.map((f) => (
              <PriceInput
                key={f.key}
                label={f.label}
                error={errors[f.key]?.message}
                registration={form.register(f.key)}
                disabled={pending}
              />
            ))}
          </div>
          {formError ? (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          ) : null}
        </form>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="price-form" disabled={pending}>
            {pending ? (
              <LoaderCircleIcon
                aria-hidden="true"
                data-icon="inline-start"
                className="motion-safe:animate-spin"
              />
            ) : null}
            {pending ? "Saving…" : "Save price"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
