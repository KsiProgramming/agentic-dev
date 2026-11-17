"use client";

import { useId, type ChangeEvent } from "react";
import { Controller, type Control } from "react-hook-form";

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { formatSize } from "@/runs/artifacts/artifacts";

/** The largest spec file a run may be given (7.7), as the API checks it. */
export const MAX_SPEC_FILE_BYTES = 256 * 1024;

const EXTENSIONS = [".md", ".markdown"];

/** The spec file as the form holds it (7.7): an upload's name, size and text, or a path in the
 * run's repo. */
export interface SpecFileValues {
  source: "upload" | "repo";
  name: string;
  size: number;
  /** The upload's text; "" until a Markdown file under the cap is read. */
  content: string;
  path: string;
}

export const EMPTY_SPEC_FILE: SpecFileValues = {
  source: "upload",
  name: "",
  size: 0,
  content: "",
  path: "",
};

const isMarkdown = (name: string) => EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext));

/** Why the spec file cannot be sent as it is, or null: the API's rules, checked first here. */
export function specFileError(values: SpecFileValues): string | null {
  if (values.source === "repo") {
    const path = values.path.trim().replace(/^\/+/, "");
    if (path === "") return "Give the file's path in the repository.";
    if (path.split("/").some((part) => part === ".." || part === "." || part === "")) {
      return "Give a path from the repository's root, such as docs/spec.md.";
    }
    if (!isMarkdown(path)) return "Give a Markdown file (.md).";
    return null;
  }
  if (values.name === "") return "Pick a Markdown file.";
  if (!isMarkdown(values.name)) return "Pick a Markdown file (.md).";
  if (values.size > MAX_SPEC_FILE_BYTES) return "This file is over 256 KB.";
  if (values.content.trim() === "") return "This file is empty.";
  return null;
}

/** The `spec_file` of `POST /runs`. */
export function toSpecFile(values: SpecFileValues) {
  return values.source === "repo"
    ? { source: "repo" as const, path: values.path.trim() }
    : { source: "upload" as const, name: values.name, content: values.content };
}

const REFUSALS = [
  "spec_file_required",
  "spec_file_invalid",
  "path_invalid",
  "path_not_found",
  "not_a_file",
];

/** The reason of a `POST /runs` refusal about the spec file (`<code>: <reason>`), or null. */
export function specFileRefusal(message: string | null | undefined): string | null {
  const code = message?.split(":", 1)[0];
  if (!message || !code || !REFUSALS.includes(code)) return null;
  return message.slice(code.length + 1).trim();
}

/**
 * The spec file a run is given (7.7): a Markdown file uploaded from this device, or a path in the
 * run's repository, read at its branch when the run starts. The file's text is never shown or
 * rendered here; the run console shows it, as sanitised Markdown.
 */
export function SpecFileField<T extends { specFile: SpecFileValues }>({
  control,
  label,
  description,
  example,
  disabled,
}: {
  control: Control<T>;
  label: string;
  description?: string | null;
  example?: string | null;
  disabled: boolean;
}) {
  const id = useId();
  // react-hook-form's paths cannot be typed through a generic form here.
  const typed = control as unknown as Control<{ specFile: SpecFileValues }>;
  return (
    <Controller
      name="specFile"
      control={typed}
      render={({ field, fieldState }) => {
        const value = field.value;
        const error = fieldState.error?.message;
        const described = error ? `${id}-error` : `${id}-help`;
        async function pick(event: ChangeEvent<HTMLInputElement>) {
          const file = event.target.files?.[0];
          if (!file) {
            field.onChange({ ...value, name: "", size: 0, content: "" });
            return;
          }
          const readable = isMarkdown(file.name) && file.size <= MAX_SPEC_FILE_BYTES;
          const content = readable ? await file.text() : "";
          field.onChange({ ...value, name: file.name, size: file.size, content });
        }
        const help =
          value.source === "upload"
            ? value.name
              ? `${value.name} · ${formatSize(value.size)}`
              : (description ?? "A Markdown file, up to 256 KB.")
            : "Read from the repository's branch when the run starts.";
        return (
          <Field data-invalid={error ? true : undefined}>
            <FieldLabel id={`${id}-label`}>{label}</FieldLabel>
            <Tabs
              value={value.source}
              onValueChange={(source) =>
                field.onChange({ ...value, source: source as SpecFileValues["source"] })
              }
              className="gap-3"
            >
              <TabsList variant="segmented" aria-labelledby={`${id}-label`} className="w-full">
                <TabsTrigger value="upload" disabled={disabled}>
                  Upload
                </TabsTrigger>
                <TabsTrigger value="repo" disabled={disabled}>
                  From the repo
                </TabsTrigger>
              </TabsList>
              <TabsContent value="upload">
                <Input
                  id={`${id}-file`}
                  type="file"
                  accept=".md,.markdown,text/markdown"
                  aria-label={`${label}: Markdown file`}
                  aria-required="true"
                  aria-invalid={error ? true : undefined}
                  aria-describedby={described}
                  disabled={disabled}
                  onChange={(event) => void pick(event)}
                />
              </TabsContent>
              <TabsContent value="repo">
                <Input
                  id={`${id}-path`}
                  className="font-mono"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={`e.g. ${example ?? "docs/spec.md"}`}
                  aria-label={`${label}: path in the repository`}
                  aria-required="true"
                  aria-invalid={error ? true : undefined}
                  aria-describedby={described}
                  disabled={disabled}
                  value={value.path}
                  onChange={(event) => field.onChange({ ...value, path: event.target.value })}
                  onBlur={field.onBlur}
                />
              </TabsContent>
            </Tabs>
            {error ? (
              <FieldMessage id={`${id}-error`}>{error}</FieldMessage>
            ) : (
              <FieldDescription id={`${id}-help`}>{help}</FieldDescription>
            )}
          </Field>
        );
      }}
    />
  );
}
