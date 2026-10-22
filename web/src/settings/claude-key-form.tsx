"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircleIcon } from "lucide-react";
import { useId } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/api/errors";
import { useSaveClaudeKey, type Connection } from "@/api/queries";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { FieldMessage } from "@/forms/schema-form/schema-fields";

const schema = z.object({
  apiKey: z
    .string()
    .trim()
    .min(1, "Paste your Claude API key.")
    .min(8, "That is too short to be an API key.")
    .max(512, "That is too long to be an API key."),
});

type Values = z.infer<typeof schema>;

/** Saves the workspace's Claude API key. The API checks it with Anthropic first: a key it
 * refuses shows on the field and is not stored. Used on Settings and in the "New run" sheet. */
export function ClaudeKeyForm({
  workspaceId,
  baseUrl,
  submitLabel = "Save key",
  onSaved,
  onCancel,
}: {
  workspaceId: string;
  baseUrl?: string;
  submitLabel?: string;
  onSaved?: (connection: Connection) => void;
  onCancel?: () => void;
}) {
  const id = useId();
  const save = useSaveClaudeKey({ workspaceId, baseUrl });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { apiKey: "" } });
  const error = form.formState.errors.apiKey?.message;

  async function onSubmit({ apiKey }: Values) {
    try {
      const connection = await save.mutateAsync(apiKey);
      form.reset();
      toast.success("Claude key saved.");
      onSaved?.(connection);
    } catch (err) {
      if (!(err instanceof ApiError)) return; // Shown below from `save.error`.
      if (err.code === "invalid_key" || err.code === "verify_unavailable") {
        form.setError("apiKey", { message: err.message });
      } else if (err.status === 422) {
        form.setError("apiKey", { message: "That does not look like an API key." });
      }
    }
  }

  // Errors on the key are shown on its field; any other failure above the buttons.
  const formError =
    save.error &&
    !(save.error instanceof ApiError && (save.error.status === 422 || save.error.code))
      ? save.error.message
      : null;
  const pending = form.formState.isSubmitting;

  return (
    <form
      onSubmit={(e) => void form.handleSubmit(onSubmit)(e)}
      className="flex w-full max-w-md flex-col gap-3"
      noValidate
    >
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor={id}>Claude API key</FieldLabel>
        <Input
          id={id}
          type="password"
          autoComplete="off"
          placeholder="sk-ant-…"
          className="font-mono"
          aria-invalid={error ? true : undefined}
          aria-describedby={[`${id}-help`, error ? `${id}-error` : null].filter(Boolean).join(" ")}
          disabled={pending}
          {...form.register("apiKey")}
        />
        <FieldDescription id={`${id}-help`}>
          From the Anthropic Console. It is checked, then stored encrypted and never shown again.
        </FieldDescription>
        {error ? <FieldMessage id={`${id}-error`}>{error}</FieldMessage> : null}
      </Field>
      {formError ? (
        <Alert variant="destructive">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : null}
          {pending ? "Checking…" : submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}
