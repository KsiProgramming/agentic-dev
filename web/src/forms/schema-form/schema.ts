/**
 * A template's options form, read from its JSON Schema (`GET /templates` → `parameters`, made by
 * Pydantic). Only the subset templates use is supported; anything else is refused, so a new
 * kind of option shows an error instead of a form that silently drops it.
 *
 * Form values are strings and booleans (what inputs hold). `toZod` checks them against the
 * schema's limits and turns them into the template's `parameters`: a list is one item per line
 * (a list of choices too, one checked option per line), a whole number is a number, and an empty
 * optional field is left out, so the server applies its default.
 */
import { z } from "zod";

interface Common {
  name: string;
  label: string;
  description?: string;
  required: boolean;
}

export type FieldSpec =
  | (Common & {
      kind: "string";
      default?: string;
      minLength?: number;
      maxLength?: number;
      pattern?: string;
      /** Long text: a textarea. */
      multiline: boolean;
    })
  | (Common & {
      kind: "string-list";
      default?: string[];
      maxItems?: number;
      itemMinLength?: number;
      itemMaxLength?: number;
    })
  | (Common & { kind: "enum"; default?: string; options: string[] })
  /** A list of choices (`array` of `enum`): one checkbox per option. */
  | (Common & {
      kind: "enum-list";
      default?: string[];
      options: string[];
      minItems?: number;
      maxItems?: number;
    })
  | (Common & { kind: "integer"; default?: number; minimum?: number; maximum?: number })
  | (Common & { kind: "boolean"; default?: boolean });

export type FormValues = Record<string, string | boolean>;
export type Parameters = Record<string, string | string[] | number | boolean>;

/** Above this many characters a string option is edited in a textarea. */
const MULTILINE_FROM = 200;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function str(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/** "Extra Instructions" (Pydantic's title) → "Extra instructions". */
export function sentenceCase(title: string): string {
  const lower = title.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/** `anyOf: [X, {type: "null"}]` (an optional field in Pydantic) is X. */
function unwrapOptional(property: Json): Json | null {
  const anyOf = property.anyOf;
  if (!Array.isArray(anyOf)) return property;
  const kinds = anyOf.filter(isObject);
  const nonNull = kinds.filter((k) => k.type !== "null");
  if (kinds.length !== anyOf.length || nonNull.length !== 1) return null;
  return { ...property, ...nonNull[0], anyOf: undefined };
}

function field(name: string, raw: unknown, required: boolean): FieldSpec | string {
  if (!isObject(raw)) return `option ${name} has no schema`;
  const property = unwrapOptional(raw);
  if (property === null) return `option ${name} accepts several kinds of value`;
  const common: Common = {
    name,
    label: sentenceCase(str(property.title) ?? name.replaceAll("_", " ")),
    description: str(property.description),
    required,
  };
  const fallback = property.default;
  if (Array.isArray(property.enum)) {
    const options = property.enum.filter((o): o is string => typeof o === "string");
    if (options.length !== property.enum.length) return `option ${name} has non-text choices`;
    return { ...common, kind: "enum", options, default: str(fallback) };
  }
  switch (property.type) {
    case "string": {
      if (property.format !== undefined) return `option ${name} has an unsupported format`;
      const maxLength = num(property.maxLength);
      return {
        ...common,
        kind: "string",
        default: str(fallback),
        minLength: num(property.minLength),
        maxLength,
        pattern: str(property.pattern),
        multiline: maxLength === undefined || maxLength > MULTILINE_FROM,
      };
    }
    case "boolean":
      return {
        ...common,
        kind: "boolean",
        default: typeof fallback === "boolean" ? fallback : undefined,
      };
    case "integer":
      return {
        ...common,
        kind: "integer",
        default: typeof fallback === "number" ? fallback : undefined,
        minimum: num(property.minimum),
        maximum: num(property.maximum),
      };
    case "array": {
      const items = property.items;
      if (!isObject(items) || items.type !== "string")
        return `option ${name} is not a list of text`;
      if (Array.isArray(items.enum)) {
        const options = items.enum.filter((o): o is string => typeof o === "string");
        if (options.length !== items.enum.length) return `option ${name} has non-text choices`;
        return {
          ...common,
          kind: "enum-list",
          options,
          default: Array.isArray(fallback)
            ? fallback.filter((v): v is string => typeof v === "string")
            : undefined,
          minItems: num(property.minItems),
          maxItems: num(property.maxItems),
        };
      }
      return {
        ...common,
        kind: "string-list",
        default: Array.isArray(fallback)
          ? fallback.filter((v) => typeof v === "string")
          : undefined,
        maxItems: num(property.maxItems),
        itemMinLength: num(items.minLength),
        itemMaxLength: num(items.maxLength),
      };
    }
    default:
      return `option ${name} has an unsupported type`;
  }
}

/** The fields of an options schema, in its order, or why it cannot be shown. */
export function parseSchema(schema: unknown): { fields: FieldSpec[] } | { error: string } {
  if (!isObject(schema) || schema.type !== "object")
    return { error: "the options are not an object" };
  const properties = isObject(schema.properties) ? schema.properties : {};
  const required = new Set(Array.isArray(schema.required) ? schema.required : []);
  const fields: FieldSpec[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    const parsed = field(name, raw, required.has(name));
    if (typeof parsed === "string") return { error: parsed };
    fields.push(parsed);
  }
  return { fields };
}

/** The form's starting values: each field's default, or empty. */
export function defaultValues(fields: FieldSpec[]): FormValues {
  return Object.fromEntries(
    fields.map((f) => {
      switch (f.kind) {
        case "boolean":
          return [f.name, f.default ?? false];
        case "string-list":
        case "enum-list":
          return [f.name, (f.default ?? []).join("\n")];
        case "integer":
          return [f.name, f.default === undefined ? "" : String(f.default)];
        default:
          return [f.name, f.default ?? ""];
      }
    }),
  );
}

/** The non-empty lines of a list field, trimmed. */
export function listItems(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function patternOf(source: string): RegExp | null {
  try {
    return new RegExp(source);
  } catch {
    // A Python-only construct: the server still checks it.
    return null;
  }
}

function stringField(f: Extract<FieldSpec, { kind: "string" }>) {
  const pattern = f.pattern ? patternOf(f.pattern) : null;
  return z.string().superRefine((value, ctx) => {
    const text = value.trim();
    if (text === "") {
      if (f.required) ctx.addIssue({ code: "custom", message: `${f.label} is required.` });
      return;
    }
    if (f.minLength !== undefined && text.length < f.minLength) {
      ctx.addIssue({ code: "custom", message: `Use at least ${f.minLength} characters.` });
    }
    if (f.maxLength !== undefined && text.length > f.maxLength) {
      ctx.addIssue({ code: "custom", message: `Use at most ${f.maxLength} characters.` });
    }
    if (pattern && !pattern.test(text)) {
      ctx.addIssue({ code: "custom", message: "This is not in the expected format." });
    }
  });
}

function listField(f: Extract<FieldSpec, { kind: "string-list" }>) {
  return z.string().superRefine((value, ctx) => {
    const items = listItems(value);
    if (items.length === 0 && f.required) {
      ctx.addIssue({ code: "custom", message: `${f.label} is required.` });
    }
    if (f.maxItems !== undefined && items.length > f.maxItems) {
      ctx.addIssue({ code: "custom", message: `Use at most ${f.maxItems} lines.` });
    }
    const max = f.itemMaxLength;
    const long = max === undefined ? undefined : items.find((item) => item.length > max);
    if (long !== undefined) {
      ctx.addIssue({ code: "custom", message: `Each line can have at most ${max} characters.` });
    }
  });
}

function enumListField(f: Extract<FieldSpec, { kind: "enum-list" }>) {
  return z.string().superRefine((value, ctx) => {
    const picked = listItems(value);
    const min = f.minItems ?? (f.required ? 1 : 0);
    if (picked.length < min) {
      ctx.addIssue({
        code: "custom",
        message: min === 1 ? "Pick at least one." : `Pick at least ${min}.`,
      });
    }
    if (f.maxItems !== undefined && picked.length > f.maxItems) {
      ctx.addIssue({ code: "custom", message: `Pick at most ${f.maxItems}.` });
    }
  });
}

function integerField(f: Extract<FieldSpec, { kind: "integer" }>) {
  return z.string().superRefine((value, ctx) => {
    const text = value.trim();
    if (text === "") {
      if (f.required) ctx.addIssue({ code: "custom", message: `${f.label} is required.` });
      return;
    }
    const n = Number(text);
    if (!/^-?\d+$/.test(text) || !Number.isSafeInteger(n)) {
      ctx.addIssue({ code: "custom", message: "Enter a whole number." });
      return;
    }
    if (f.minimum !== undefined && n < f.minimum) {
      ctx.addIssue({ code: "custom", message: `Use ${f.minimum} or more.` });
    }
    if (f.maximum !== undefined && n > f.maximum) {
      ctx.addIssue({ code: "custom", message: `Use ${f.maximum} or less.` });
    }
  });
}

/** Checks the form's values against the schema's limits (`toParameters` then turns them into
 * the template's `parameters`). */
export function toZod(fields: FieldSpec[]) {
  const shape: Record<string, z.ZodType<string | boolean>> = {};
  for (const f of fields) {
    switch (f.kind) {
      case "string":
        shape[f.name] = stringField(f);
        break;
      case "string-list":
        shape[f.name] = listField(f);
        break;
      case "enum-list":
        shape[f.name] = enumListField(f);
        break;
      case "integer":
        shape[f.name] = integerField(f);
        break;
      case "enum":
        shape[f.name] = f.required
          ? z.string().refine((v) => f.options.includes(v), { message: "Pick one of the options." })
          : z.string().refine((v) => v === "" || f.options.includes(v), {
              message: "Pick one of the options.",
            });
        break;
      case "boolean":
        shape[f.name] = z.boolean();
        break;
    }
  }
  // The shape is built at runtime, so zod cannot infer it: every value is a string or boolean.
  return z.object(shape) as unknown as z.ZodType<FormValues, FormValues>;
}

/** The template's `parameters` for valid form values. Empty optional fields are left out. */
export function toParameters(fields: FieldSpec[], values: FormValues): Parameters {
  const parameters: Parameters = {};
  for (const f of fields) {
    const value = values[f.name];
    if (f.kind === "boolean") {
      parameters[f.name] = value === true;
    } else if (f.kind === "string-list") {
      const items = listItems(String(value ?? ""));
      if (items.length > 0) parameters[f.name] = items;
    } else if (f.kind === "enum-list") {
      // Every option a template offers, in its order: unchecking them all is a choice too.
      const picked = new Set(listItems(String(value ?? "")));
      parameters[f.name] = f.options.filter((o) => picked.has(o));
    } else if (f.kind === "integer") {
      const text = String(value ?? "").trim();
      if (text !== "") parameters[f.name] = Number(text);
    } else {
      const text = String(value ?? "").trim();
      if (text !== "") parameters[f.name] = text;
    }
  }
  return parameters;
}

/**
 * The template option errors in a refused `POST /runs`: its 422 says
 * `parameters.<name>[.<index>]: <why>`, joined by `; `. Returns them by option name, and the
 * rest of the message (or null).
 */
export function parameterErrors(message: string): {
  byField: Record<string, string>;
  rest: string | null;
} {
  const byField: Record<string, string> = {};
  const rest: string[] = [];
  const text = message.replace(/^Value error, /, "");
  for (const part of text.split("; ")) {
    const match = /^parameters\.([A-Za-z0-9_]+)(?:\.[^:]*)?: (.*)$/.exec(part);
    if (match?.[1] && match[2]) byField[match[1]] ??= match[2];
    else if (part.trim()) rest.push(part.trim());
  }
  return { byField, rest: rest.length > 0 ? rest.join("; ") : null };
}
