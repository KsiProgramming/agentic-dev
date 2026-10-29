"use client";

import { useId } from "react";
import { Controller, type Control } from "react-hook-form";

import type { NewRepoOptions } from "@/api/queries";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { FieldMessage } from "@/forms/schema-form/schema-fields";

/** The new repo as the form holds it: "" for an option left out. */
export interface NewRepoValues {
  name: string;
  private: boolean;
  description: string;
  gitignore: string;
  license: string;
}

export const EMPTY_NEW_REPO: NewRepoValues = {
  name: "",
  private: true,
  description: "",
  gitignore: "",
  license: "",
};

const NAME = /^[A-Za-z0-9._-]{1,100}$/;

/** Why `name` cannot name a GitHub repo, or null if it can (the API's rules). */
export function newRepoNameError(name: string): string | null {
  if (name === "") return "Name the new repository.";
  if (name === "." || name === "..") return "A repository cannot be named . or ..";
  if (!NAME.test(name)) return "Use letters, digits, ., - and _ only, up to 100 characters.";
  return null;
}

const LICENSE_NAMES: Record<string, string> = { mit: "MIT", "apache-2.0": "Apache 2.0" };

/** The `new_repo` of `POST /runs`. */
export function toNewRepo(values: NewRepoValues) {
  return {
    name: values.name,
    private: values.private,
    description: values.description.trim() || null,
    gitignore: (values.gitignore || null) as NewRepoOptions["gitignore_templates"][number] | null,
    license: (values.license || null) as NewRepoOptions["licenses"][number] | null,
  };
}

/** The new repo's name, visibility, description and what its first commit holds. */
export function NewRepoFields<T extends { newRepo: NewRepoValues }>({
  control,
  options,
  disabled,
}: {
  control: Control<T>;
  options: NewRepoOptions;
  disabled: boolean;
}) {
  const id = useId();
  // react-hook-form's paths cannot be typed through a generic form here.
  const typed = control as unknown as Control<{ newRepo: NewRepoValues }>;
  return (
    <div className="flex flex-col gap-4">
      <Controller
        name="newRepo.name"
        control={typed}
        render={({ field, fieldState }) => (
          <Field data-invalid={fieldState.error ? true : undefined}>
            <FieldLabel htmlFor={`${id}-name`}>Repository name</FieldLabel>
            <div className="flex min-w-0 items-center gap-1 font-mono text-meta">
              <span className="shrink-0 text-muted-foreground">{options.owner}/</span>
              <Input
                id={`${id}-name`}
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
                aria-invalid={fieldState.error ? true : undefined}
                aria-describedby={fieldState.error ? `${id}-name-error` : `${id}-name-help`}
                disabled={disabled}
                {...field}
              />
            </div>
            {fieldState.error?.message ? (
              <FieldMessage id={`${id}-name-error`}>{fieldState.error.message}</FieldMessage>
            ) : (
              <FieldDescription id={`${id}-name-help`}>
                Created in {options.owner} once you approve, then the run works on it.
              </FieldDescription>
            )}
          </Field>
        )}
      />
      <Controller
        name="newRepo.private"
        control={typed}
        render={({ field }) => (
          <Field orientation="horizontal">
            <Checkbox
              id={`${id}-private`}
              name={field.name}
              checked={field.value}
              onCheckedChange={(checked) => field.onChange(checked === true)}
              onBlur={field.onBlur}
              aria-describedby={`${id}-private-help`}
              disabled={disabled}
            />
            <FieldContent>
              <FieldLabel htmlFor={`${id}-private`}>Private</FieldLabel>
              <FieldDescription id={`${id}-private-help`}>
                Only members of {options.owner} can see it.
              </FieldDescription>
            </FieldContent>
          </Field>
        )}
      />
      <Controller
        name="newRepo.description"
        control={typed}
        render={({ field, fieldState }) => (
          <Field data-invalid={fieldState.error ? true : undefined}>
            <FieldLabel htmlFor={`${id}-description`}>Description (optional)</FieldLabel>
            <Input
              id={`${id}-description`}
              autoComplete="off"
              maxLength={350}
              aria-invalid={fieldState.error ? true : undefined}
              aria-describedby={fieldState.error ? `${id}-description-error` : undefined}
              disabled={disabled}
              {...field}
            />
            {fieldState.error?.message ? (
              <FieldMessage id={`${id}-description-error`}>{fieldState.error.message}</FieldMessage>
            ) : null}
          </Field>
        )}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Controller
          name="newRepo.gitignore"
          control={typed}
          render={({ field }) => (
            <Field>
              <FieldLabel htmlFor={`${id}-gitignore`}>.gitignore</FieldLabel>
              <NativeSelect id={`${id}-gitignore`} disabled={disabled} {...field}>
                <NativeSelectOption value="">None</NativeSelectOption>
                {options.gitignore_templates.map((t) => (
                  <NativeSelectOption key={t} value={t}>
                    {t}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
          )}
        />
        <Controller
          name="newRepo.license"
          control={typed}
          render={({ field }) => (
            <Field>
              <FieldLabel htmlFor={`${id}-license`}>License</FieldLabel>
              <NativeSelect id={`${id}-license`} disabled={disabled} {...field}>
                <NativeSelectOption value="">None</NativeSelectOption>
                {options.licenses.map((l) => (
                  <NativeSelectOption key={l} value={l}>
                    {LICENSE_NAMES[l] ?? l}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
          )}
        />
      </div>
    </div>
  );
}
