import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import { FINDINGS_PROPERTIES, portMismatches } from "./ports";

/** The cases the engine also runs (`test_port_check_fixtures.py`), so the canvas blocks the
 * connections the server would report. */
interface Case {
  name: string;
  spec: WorkflowSpec;
  mismatches: string[];
}

const read = (path: string) => JSON.parse(readFileSync(resolve(__dirname, path), "utf8"));
const doc = read("../../../schemas/fixtures/port-checks.json") as { cases: Case[] };

describe("portMismatches", () => {
  it.each(doc.cases.map((c) => [c.name, c] as const))("%s, as the engine finds", (_, c) => {
    expect(portMismatches(c.spec).map((m) => m.consumer)).toEqual(c.mismatches);
  });

  it("words a mismatch as the engine does", () => {
    const [found] = portMismatches(doc.cases[1].spec);
    expect(found).toEqual({
      producer: "p",
      consumer: "c",
      message:
        "agent 'c': input_schema requires 'b', which the output_schema of 'p' does not declare",
      reason:
        "The input_schema of 'c' requires 'b', which the output_schema of 'p' does not declare.",
    });
  });

  it("knows the findings report's top-level property types", () => {
    const schema = read("../../../schemas/findings.v1.json") as {
      properties: Record<string, { type?: string | string[] }>;
    };
    const types = Object.fromEntries(
      Object.entries(schema.properties).map(([name, p]) => [
        name,
        p.type === undefined ? [] : [p.type].flat(),
      ]),
    );
    expect(FINDINGS_PROPERTIES).toEqual(types);
  });
});
