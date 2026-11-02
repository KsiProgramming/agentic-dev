import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { applyOps, OpError, type GraphOp } from "./ops";

/** The cases the engine also runs (`test_graph_ops_fixtures.py`), so the builder's preview is
 * what the server will store. */
interface Case {
  name: string;
  ops: GraphOp[];
  result?: unknown;
  error?: { code: string; op_index: number | null; node_id: string | null };
}

const doc = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/graph-ops.json"), "utf8"),
) as { spec: unknown; cases: Case[] };

describe("applyOps", () => {
  it.each(doc.cases.map((c) => [c.name, c] as const))("%s, as the engine does", (_, c) => {
    const before = structuredClone(doc.spec);
    if (c.result !== undefined) {
      expect(applyOps(doc.spec, c.ops)).toEqual(c.result);
    } else {
      let error: unknown;
      try {
        applyOps(doc.spec, c.ops);
      } catch (e) {
        error = e;
      }
      expect(error).toBeInstanceOf(OpError);
      const { code, op_index, node_id } = error as OpError;
      expect({ code, op_index, node_id }).toEqual(c.error);
    }
    expect(doc.spec).toEqual(before);
  });
});
