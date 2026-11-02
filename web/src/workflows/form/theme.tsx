"use client";

import type { FormProps } from "@rjsf/core";
import {
  ariaDescribedByIds,
  descriptionId,
  enumOptionsDeselectValue,
  enumOptionsIndexForValue,
  enumOptionsIsSelected,
  enumOptionsSelectValue,
  enumOptionsValueForIndex,
  errorId,
  getInputProps,
  getUiOptions,
  type ArrayFieldItemTemplateProps,
  type ArrayFieldTemplateProps,
  type BaseInputTemplateProps,
  type FieldProps,
  type FieldTemplateProps,
  type ObjectFieldTemplateProps,
  type RegistryFieldsType,
  type RegistryWidgetsType,
  type TemplatesType,
  type WidgetProps,
} from "@rjsf/utils";
import { ChevronRightIcon, CircleAlertIcon, PlusIcon, XIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { FieldDescription } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/**
 * The side panel's form theme (5.4): `@rjsf/core` drawn with this app's primitives, tokens and
 * type scale. No rjsf stylesheet is used. A manifest's `ui` picks among these by name
 * (`textarea`, `checkboxes`, `json`); see tech-stack → Node manifests.
 */

/** Schema descriptions are written for the spec (with `code` in backticks); shown as text. */
function plain(text: string | undefined): string {
  return (text ?? "").replaceAll("`", "");
}

function FieldErrors({ id, errors }: { id: string; errors?: string[] }) {
  if (!errors?.length) return null;
  return (
    <p
      id={errorId(id)}
      role="alert"
      className="flex items-start gap-1 text-caption text-status-failed"
    >
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
      <span>{errors[0]}</span>
    </p>
  );
}

function FieldLabelText({
  htmlFor,
  label,
  required,
}: {
  htmlFor?: string;
  label: string;
  required?: boolean;
}) {
  return (
    <Label htmlFor={htmlFor} className="text-meta font-medium text-foreground">
      {label}
      {required ? null : <span className="font-normal text-muted-foreground"> Optional</span>}
    </Label>
  );
}

function FieldTemplate(props: FieldTemplateProps) {
  const { id, label, displayLabel, required, rawDescription, rawErrors, children, hidden } = props;
  if (hidden) return <div className="hidden">{children}</div>;
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-field={id}>
      {displayLabel && label ? (
        <FieldLabelText htmlFor={id} label={label} required={required} />
      ) : null}
      {children}
      {displayLabel && rawDescription ? (
        <FieldDescription id={descriptionId(id)}>{plain(rawDescription)}</FieldDescription>
      ) : null}
      {displayLabel ? <FieldErrors id={id} errors={rawErrors} /> : null}
    </div>
  );
}

/** An object's fields, with those the `ui` marks `advanced` in a collapsed group. The form's
 * own root has no frame or title (the panel's header names the node). */
function ObjectFieldTemplate(props: ObjectFieldTemplateProps) {
  const { title, description, properties, uiSchema, required, fieldPathId } = props;
  const isAdvanced = (name: string) =>
    Boolean(getUiOptions((uiSchema?.[name] ?? {}) as never).advanced);
  const visible = properties.filter((p) => !p.hidden);
  const main = visible.filter((p) => !isAdvanced(p.name));
  const advanced = visible.filter((p) => isAdvanced(p.name));
  const body = (
    <div className="flex flex-col gap-4">
      {main.map((p) => (
        <div key={p.name}>{p.content}</div>
      ))}
      {advanced.length > 0 ? (
        <AdvancedGroup>
          {advanced.map((p) => (
            <div key={p.name}>{p.content}</div>
          ))}
        </AdvancedGroup>
      ) : null}
    </div>
  );
  if (fieldPathId.path.length === 0) return body;
  const text = typeof description === "string" ? description : undefined;
  return (
    <fieldset className="flex min-w-0 flex-col gap-3 rounded-md border p-3">
      {title ? (
        <legend className="px-1 text-meta font-medium text-foreground">
          {title}
          {required ? null : (
            <span className="ml-2 font-normal text-muted-foreground"> Optional</span>
          )}
        </legend>
      ) : null}
      {text ? <FieldDescription>{plain(text)}</FieldDescription> : null}
      {body}
    </fieldset>
  );
}

function AdvancedGroup({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col gap-4">
      <CollapsibleTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start px-0 text-muted-foreground"
        >
          <ChevronRightIcon
            aria-hidden="true"
            className={cn("transition-transform", open && "rotate-90")}
          />
          Advanced
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function ArrayFieldTemplate(props: ArrayFieldTemplateProps) {
  const {
    title,
    items,
    canAdd,
    onAddClick,
    required,
    schema,
    fieldPathId,
    rawErrors,
    disabled,
    readonly,
  } = props;
  const id = fieldPathId.$id;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      {title ? <FieldLabelText label={title} required={required} /> : null}
      {schema.description ? <FieldDescription>{plain(schema.description)}</FieldDescription> : null}
      {items.length > 0 ? <div className="flex flex-col gap-2">{items}</div> : null}
      {canAdd ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          disabled={disabled || readonly}
          onClick={onAddClick}
        >
          <PlusIcon aria-hidden="true" data-icon="inline-start" />
          Add
        </Button>
      ) : null}
      <FieldErrors id={id} errors={rawErrors} />
    </div>
  );
}

function ArrayFieldItemTemplate(props: ArrayFieldItemTemplateProps) {
  const { children, buttonsProps, index } = props;
  return (
    <div className="flex min-w-0 items-start gap-2">
      <div className="min-w-0 flex-1">{children}</div>
      {buttonsProps.hasRemove ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`Remove item ${index + 1}`}
          disabled={buttonsProps.disabled || buttonsProps.readonly}
          onClick={buttonsProps.onRemoveItem}
        >
          <XIcon aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
}

function BaseInputTemplate(props: BaseInputTemplateProps) {
  const {
    id,
    value,
    required,
    disabled,
    readonly,
    autofocus,
    placeholder,
    onChange,
    onBlur,
    onFocus,
    options,
    schema,
    type,
    rawErrors,
  } = props;
  const inputProps = getInputProps(schema, type, options);
  const empty = options.emptyValue;
  return (
    <Input
      id={id}
      name={id}
      {...inputProps}
      className={cn(inputProps.type === "number" && "tabular-nums", schema.pattern && "font-mono")}
      value={value ?? ""}
      required={required}
      disabled={disabled}
      readOnly={readonly}
      autoFocus={autofocus}
      placeholder={placeholder}
      aria-invalid={rawErrors?.length ? true : undefined}
      aria-describedby={ariaDescribedByIds(id)}
      onChange={(e) => onChange(e.target.value === "" ? empty : e.target.value)}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
    />
  );
}

function TextareaWidget(props: WidgetProps) {
  const {
    id,
    value,
    required,
    disabled,
    readonly,
    placeholder,
    onChange,
    onBlur,
    onFocus,
    options,
    rawErrors,
  } = props;
  return (
    <Textarea
      id={id}
      name={id}
      value={value ?? ""}
      rows={typeof options.rows === "number" ? options.rows : 5}
      required={required}
      disabled={disabled}
      readOnly={readonly}
      placeholder={placeholder}
      aria-invalid={rawErrors?.length ? true : undefined}
      aria-describedby={ariaDescribedByIds(id)}
      onChange={(e) => onChange(e.target.value === "" ? options.emptyValue : e.target.value)}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
    />
  );
}

function SelectWidget(props: WidgetProps) {
  const {
    id,
    value,
    required,
    disabled,
    readonly,
    onChange,
    onBlur,
    onFocus,
    options,
    placeholder,
    rawErrors,
  } = props;
  const enumOptions = options.enumOptions ?? [];
  const selected = enumOptionsIndexForValue(value, enumOptions, false);
  const toValue = (index: string) =>
    index === "" ? options.emptyValue : enumOptionsValueForIndex(index, enumOptions);
  return (
    <NativeSelect
      id={id}
      name={id}
      className="w-full"
      value={typeof selected === "undefined" ? "" : String(selected)}
      required={required}
      disabled={disabled || readonly}
      aria-invalid={rawErrors?.length ? true : undefined}
      aria-describedby={ariaDescribedByIds(id)}
      onChange={(e) => onChange(toValue(e.target.value))}
      onBlur={(e) => onBlur(id, toValue(e.target.value))}
      onFocus={(e) => onFocus(id, toValue(e.target.value))}
    >
      {required ? null : (
        <NativeSelectOption value="">{placeholder || "Not set"}</NativeSelectOption>
      )}
      {enumOptions.map((option, i) => (
        <NativeSelectOption key={i} value={String(i)}>
          {String(option.label)}
        </NativeSelectOption>
      ))}
    </NativeSelect>
  );
}

function CheckboxWidget(props: WidgetProps) {
  const { id, value, label, disabled, readonly, onChange, schema } = props;
  return (
    <div className="flex items-start gap-2">
      <Checkbox
        id={id}
        checked={value === true}
        disabled={disabled || readonly}
        aria-describedby={ariaDescribedByIds(id)}
        onCheckedChange={(checked) => onChange(checked === true)}
      />
      <Label htmlFor={id} className="text-meta font-medium">
        {label || schema.title}
      </Label>
    </div>
  );
}

/** A list of choices (an agent's tools), one checkbox each; ids and tool names in mono. */
function CheckboxesWidget(props: WidgetProps) {
  const { id, value, disabled, readonly, onChange, options } = props;
  const enumOptions = options.enumOptions ?? [];
  const chosen = Array.isArray(value) ? value : [];
  return (
    <div
      role="group"
      aria-describedby={ariaDescribedByIds(id)}
      className="grid gap-2 @sm:grid-cols-2"
    >
      {enumOptions.map((option, i) => {
        const optionId = `${id}-${i}`;
        const checked = enumOptionsIsSelected(option.value, chosen);
        return (
          <div key={optionId} className="flex min-w-0 items-center gap-2">
            <Checkbox
              id={optionId}
              checked={checked}
              disabled={disabled || readonly}
              onCheckedChange={(next) =>
                onChange(
                  next === true
                    ? enumOptionsSelectValue(i, chosen, enumOptions)
                    : enumOptionsDeselectValue(i, chosen, enumOptions),
                )
              }
            />
            <Label
              htmlFor={optionId}
              className="min-w-0 truncate font-mono text-caption font-normal"
            >
              {String(option.label)}
            </Label>
          </div>
        );
      })}
    </div>
  );
}

/** A USD amount (the workflow's budget): a number with a `$` before it. */
function UsdWidget(props: WidgetProps) {
  const {
    id,
    value,
    required,
    disabled,
    readonly,
    placeholder,
    onChange,
    onBlur,
    rawErrors,
    schema,
  } = props;
  return (
    <InputGroup>
      <InputGroupAddon align="inline-start" aria-hidden="true">
        <InputGroupText>$</InputGroupText>
      </InputGroupAddon>
      <InputGroupInput
        id={id}
        name={id}
        type="number"
        inputMode="decimal"
        step="0.01"
        min={schema.minimum}
        max={schema.maximum}
        className="tabular-nums"
        value={value ?? ""}
        required={required}
        disabled={disabled}
        readOnly={readonly}
        placeholder={placeholder}
        aria-invalid={rawErrors?.length ? true : undefined}
        aria-describedby={ariaDescribedByIds(id)}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        onBlur={(e) => onBlur(id, e.target.value)}
      />
    </InputGroup>
  );
}

/** An object edited as JSON text (a port schema, a tool's arguments). Text that does not parse,
 * or is not an object, is kept here with a message and not passed on. */
function JsonField(props: FieldProps) {
  const { formData, onChange, fieldPathId, schema, name, required, disabled, readonly, rawErrors } =
    props;
  const id = fieldPathId.$id;
  const [text, setText] = useState(() =>
    formData === undefined ? "" : JSON.stringify(formData, null, 2),
  );
  const [problem, setProblem] = useState<string | null>(null);
  const label = schema.title ?? name;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <FieldLabelText htmlFor={id} label={label} required={required} />
      <Textarea
        id={id}
        value={text}
        rows={6}
        spellCheck={false}
        className="font-mono text-caption"
        disabled={disabled}
        readOnly={readonly}
        aria-invalid={problem || rawErrors?.length ? true : undefined}
        aria-describedby={ariaDescribedByIds(id)}
        onChange={(e) => {
          const next = e.target.value;
          setText(next);
          if (next.trim() === "") {
            setProblem(null);
            onChange(undefined, fieldPathId.path);
            return;
          }
          try {
            const parsed: unknown = JSON.parse(next);
            if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
              setProblem("Must be a JSON object.");
              return;
            }
            setProblem(null);
            onChange(parsed, fieldPathId.path);
          } catch (err) {
            setProblem(`Not valid JSON: ${err instanceof Error ? err.message : String(err)}`);
          }
        }}
      />
      {schema.description ? (
        <FieldDescription id={descriptionId(id)}>{plain(schema.description)}</FieldDescription>
      ) : null}
      <FieldErrors id={id} errors={problem ? [problem] : rawErrors} />
    </div>
  );
}

export const templates: Partial<TemplatesType> = {
  FieldTemplate,
  ObjectFieldTemplate,
  ArrayFieldTemplate,
  ArrayFieldItemTemplate,
  BaseInputTemplate,
  ErrorListTemplate: () => null,
  ButtonTemplates: {
    SubmitButton: () => null,
  } as unknown as TemplatesType["ButtonTemplates"], // merged with rjsf's own by `Form`
};

export const widgets: RegistryWidgetsType = {
  TextareaWidget,
  textarea: TextareaWidget,
  SelectWidget,
  CheckboxWidget,
  CheckboxesWidget,
  checkboxes: CheckboxesWidget,
  usd: UsdWidget,
};

export const fields: RegistryFieldsType = { json: JsonField };

/** Form props every panel form shares. */
export const formDefaults = {
  templates,
  widgets,
  fields,
  noHtml5Validate: true,
  showErrorList: false,
  liveValidate: "onChange",
  experimental_defaultFormStateBehavior: { emptyObjectFields: "skipDefaults" },
} satisfies Partial<FormProps>;
