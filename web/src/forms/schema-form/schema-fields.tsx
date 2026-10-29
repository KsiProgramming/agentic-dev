"use client";

import { CircleAlertIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Controller, type Control, type FieldValues, type Path } from "react-hook-form";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";

import type { FieldSpec } from "./schema";

/** A field's error under it, with an icon, announced when it appears. */
export function FieldMessage({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} role="alert" className="flex items-start gap-1.5 text-caption text-status-failed">
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function OneField<T extends FieldValues>({
  spec,
  control,
  prefix,
  disabled,
}: {
  spec: FieldSpec;
  control: Control<T>;
  prefix?: string;
  disabled?: boolean;
}) {
  const id = useId();
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  const label = spec.required ? spec.label : `${spec.label} (optional)`;
  const help =
    spec.kind === "string-list"
      ? [spec.description, "One per line."].filter(Boolean).join(" ")
      : spec.description;

  return (
    <Controller
      name={(prefix ? `${prefix}.${spec.name}` : spec.name) as Path<T>}
      control={control}
      render={({ field, fieldState }) => {
        const invalid = fieldState.error !== undefined;
        const describedBy = [help ? helpId : null, invalid ? errorId : null]
          .filter(Boolean)
          .join(" ");
        const aria = {
          id,
          "aria-invalid": invalid || undefined,
          "aria-describedby": describedBy || undefined,
        };
        const error = fieldState.error?.message ? (
          <FieldMessage id={errorId}>{fieldState.error.message}</FieldMessage>
        ) : null;

        if (spec.kind === "boolean") {
          return (
            <Field orientation="horizontal" data-invalid={invalid || undefined}>
              <Checkbox
                {...aria}
                name={field.name}
                checked={field.value === true}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                onBlur={field.onBlur}
                disabled={disabled}
              />
              <FieldContent>
                <FieldLabel htmlFor={id}>{spec.label}</FieldLabel>
                {help ? <FieldDescription id={helpId}>{help}</FieldDescription> : null}
                {error}
              </FieldContent>
            </Field>
          );
        }

        const value = typeof field.value === "string" ? field.value : "";
        if (spec.kind === "enum-list") {
          // One checkbox per option; the value holds the checked ones, one per line.
          const picked = new Set(value.split("\n").filter(Boolean));
          const toggle = (option: string, on: boolean) => {
            const next = new Set(picked);
            if (on) next.add(option);
            else next.delete(option);
            field.onChange(spec.options.filter((o) => next.has(o)).join("\n"));
          };
          return (
            <FieldSet
              data-invalid={invalid || undefined}
              aria-describedby={describedBy || undefined}
            >
              <FieldLegend variant="label">{label}</FieldLegend>
              {help ? <FieldDescription id={helpId}>{help}</FieldDescription> : null}
              <div className="grid gap-2 sm:grid-cols-2">
                {spec.options.map((option) => {
                  const optionId = `${id}-${option}`;
                  return (
                    <Field key={option} orientation="horizontal">
                      <Checkbox
                        id={optionId}
                        name={field.name}
                        checked={picked.has(option)}
                        onCheckedChange={(checked) => toggle(option, checked === true)}
                        onBlur={field.onBlur}
                        disabled={disabled}
                      />
                      <FieldLabel htmlFor={optionId} className="font-normal">
                        {option}
                      </FieldLabel>
                    </Field>
                  );
                })}
              </div>
              {error}
            </FieldSet>
          );
        }
        let control: ReactNode;
        if (spec.kind === "enum") {
          control = (
            <NativeSelect
              {...aria}
              name={field.name}
              value={value}
              onChange={(e) => field.onChange(e.target.value)}
              onBlur={field.onBlur}
              disabled={disabled}
            >
              {spec.required ? null : <NativeSelectOption value="">Default</NativeSelectOption>}
              {spec.options.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          );
        } else if (spec.kind === "string-list" || (spec.kind === "string" && spec.multiline)) {
          control = (
            <Textarea
              {...aria}
              name={field.name}
              value={value}
              onChange={(e) => field.onChange(e.target.value)}
              onBlur={field.onBlur}
              disabled={disabled}
              rows={3}
              className={spec.kind === "string-list" ? "font-mono" : undefined}
            />
          );
        } else if (spec.kind === "integer") {
          control = (
            <Input
              {...aria}
              type="number"
              inputMode="numeric"
              step={1}
              min={spec.minimum}
              max={spec.maximum}
              name={field.name}
              value={value}
              onChange={(e) => field.onChange(e.target.value)}
              onBlur={field.onBlur}
              disabled={disabled}
              className="w-32"
            />
          );
        } else {
          control = (
            <Input
              {...aria}
              name={field.name}
              value={value}
              onChange={(e) => field.onChange(e.target.value)}
              onBlur={field.onBlur}
              disabled={disabled}
              autoComplete="off"
            />
          );
        }
        return (
          <Field data-invalid={invalid || undefined}>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            {control}
            {help ? <FieldDescription id={helpId}>{help}</FieldDescription> : null}
            {error}
          </Field>
        );
      }}
    />
  );
}

/** The inputs of a template's options, from its parsed schema (`parseSchema`). With `prefix`,
 * the values live under that key of the form (`<prefix>.<option>`). */
export function SchemaFields<T extends FieldValues>({
  fields,
  control,
  prefix,
  disabled,
}: {
  fields: FieldSpec[];
  control: Control<T>;
  prefix?: string;
  disabled?: boolean;
}) {
  return (
    <>
      {fields.map((spec) => (
        <OneField
          key={spec.name}
          spec={spec}
          control={control}
          prefix={prefix}
          disabled={disabled}
        />
      ))}
    </>
  );
}
