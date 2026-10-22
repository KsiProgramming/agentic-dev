import { expect, test } from "vitest";

import {
  defaultValues,
  parameterErrors,
  parseSchema,
  toParameters,
  toZod,
  type FieldSpec,
} from "./schema";

/** The schema Pydantic makes for the docs template's options (`DocsParams`). */
const DOCS = {
  additionalProperties: false,
  description: "The options of a docs run.",
  properties: {
    output_dir: {
      default: "docs",
      description: "Where the docs are written, relative to the repository root.",
      maxLength: 100,
      pattern: "^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*/?$",
      title: "Output Dir",
      type: "string",
    },
    include: {
      anyOf: [
        {
          items: { maxLength: 200, minLength: 1, type: "string" },
          maxItems: 20,
          type: "array",
        },
        { type: "null" },
      ],
      default: null,
      description: "Glob patterns over module paths.",
      title: "Include",
    },
    extra_instructions: {
      anyOf: [{ maxLength: 2000, type: "string" }, { type: "null" }],
      default: null,
      description: "Preferences for every agent of the run.",
      title: "Extra Instructions",
    },
  },
  title: "DocsParams",
  type: "object",
};

function fieldsOf(schema: unknown): FieldSpec[] {
  const parsed = parseSchema(schema);
  if ("error" in parsed) throw new Error(parsed.error);
  return parsed.fields;
}

test("the docs template's options become a text field, a list and a long text", () => {
  const fields = fieldsOf(DOCS);

  expect(fields.map((f) => [f.name, f.kind, f.label, f.required])).toEqual([
    ["output_dir", "string", "Output dir", false],
    ["include", "string-list", "Include", false],
    ["extra_instructions", "string", "Extra instructions", false],
  ]);
  expect(fields[0]).toMatchObject({ multiline: false, maxLength: 100, default: "docs" });
  expect(fields[1]).toMatchObject({ maxItems: 20, itemMaxLength: 200 });
  expect(fields[2]).toMatchObject({ multiline: true });
  expect(defaultValues(fields)).toEqual({
    output_dir: "docs",
    include: "",
    extra_instructions: "",
  });
});

test("enums, booleans and required fields are supported", () => {
  const fields = fieldsOf({
    type: "object",
    required: ["tone"],
    properties: {
      tone: { type: "string", enum: ["formal", "casual"], title: "Tone" },
      dry_run: { type: "boolean", default: true, title: "Dry Run" },
    },
  });

  expect(fields).toMatchObject([
    { kind: "enum", required: true, options: ["formal", "casual"] },
    { kind: "boolean", default: true, label: "Dry run" },
  ]);
  expect(toZod(fields).safeParse({ tone: "", dry_run: false }).success).toBe(false);
  expect(toZod(fields).safeParse({ tone: "casual", dry_run: false }).success).toBe(true);
});

test.each([
  [{ type: "object", properties: { n: { type: "integer" } } }, "unsupported type"],
  [
    { type: "object", properties: { n: { anyOf: [{ type: "string" }, { type: "integer" }] } } },
    "several kinds",
  ],
  [
    { type: "object", properties: { n: { type: "array", items: { type: "integer" } } } },
    "not a list of text",
  ],
  [{ type: "object", properties: { n: { type: "string", format: "date" } } }, "unsupported format"],
  [{ type: "array" }, "not an object"],
])("an unsupported schema is refused, not half shown", (schema, reason) => {
  const parsed = parseSchema(schema);

  expect("error" in parsed && parsed.error).toContain(reason);
});

test("values are checked against the schema's limits", () => {
  const schema = toZod(fieldsOf(DOCS));
  const errors = (values: Record<string, string>) => {
    const result = schema.safeParse({
      output_dir: "docs",
      include: "",
      extra_instructions: "",
      ...values,
    });
    return result.success
      ? []
      : result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
  };

  expect(errors({})).toEqual([]);
  expect(errors({ output_dir: "my docs" })).toEqual([
    "output_dir: This is not in the expected format.",
  ]);
  expect(errors({ output_dir: "d".repeat(101) })).toEqual([
    "output_dir: Use at most 100 characters.",
  ]);
  expect(errors({ include: Array.from({ length: 21 }, (_, i) => `p${i}`).join("\n") })).toEqual([
    "include: Use at most 20 lines.",
  ]);
  expect(errors({ include: "x".repeat(201) })).toEqual([
    "include: Each line can have at most 200 characters.",
  ]);
});

test("parameters leave out empty optional fields, so the server applies its defaults", () => {
  const fields = fieldsOf(DOCS);

  expect(
    toParameters(fields, {
      output_dir: " site ",
      include: "packages/*\n\n web \n",
      extra_instructions: "  ",
    }),
  ).toEqual({ output_dir: "site", include: ["packages/*", "web"] });
});

test("a refused run's option errors are read by option name", () => {
  const message =
    "Value error, parameters.output_dir: String should match pattern; parameters.include.0: " +
    "String should have at least 1 character; parameters.output_dir: second";

  expect(parameterErrors(message)).toEqual({
    byField: {
      output_dir: "String should match pattern",
      include: "String should have at least 1 character",
    },
    rest: null,
  });
  expect(parameterErrors("Value error, unknown template 'x'")).toEqual({
    byField: {},
    rest: "unknown template 'x'",
  });
});
