import { describe, expect, it } from "vitest";

import docsSpec from "../fixtures/docs-run-spec.json";
import { allSpecNodes, nodeDetail, routesOf, type SpecNode, type WorkflowSpec } from "./spec-graph";

const spec = docsSpec as WorkflowSpec;

function spec_(root: WorkflowSpec["root"]): WorkflowSpec {
  return { spec_version: "0", id: "w", name: "W", root };
}

const agent = (id: string): WorkflowSpec["root"] => ({
  type: "agent",
  id,
  role: `role of ${id}`,
  instructions: "go",
  tools: [],
});

const router: WorkflowSpec["root"] = {
  type: "sequence",
  id: "main",
  steps: [
    agent("triage"),
    {
      type: "router",
      id: "report_path",
      routes: [
        { id: "clean", when: "true", then: agent("clean_report") },
        {
          id: "fix_first",
          when: "true",
          then: { type: "sequence", id: "fix", steps: [agent("plan"), agent("fix_report")] },
        },
      ],
      default: agent("standard_report"),
    },
    agent("summary"),
  ],
};

function node(id: string, from: WorkflowSpec = spec): SpecNode {
  const found = allSpecNodes(from).find((n) => n.id === id);
  if (!found) throw new Error(`no node ${id}`);
  return found;
}

describe("nodeDetail", () => {
  it("says what each node of the docs run does", () => {
    expect(nodeDetail(node("list_modules"))).toBe("repo.list_modules");
    expect(nodeDetail(node("approve"))).toBe("Open the docs PR?");
    expect(nodeDetail(node("combine"))).toBe("Concat of document");
  });

  it("says how a router chooses", () => {
    expect(nodeDetail(node("report_path", spec_(router)))).toBe("One of 3 routes, by rules");
    const classifier = spec_({
      type: "router",
      id: "kind",
      classifier: { instructions: "Choose." },
      routes: [{ id: "bug", then: agent("fix") }],
    });
    expect(nodeDetail(node("kind", classifier))).toBe("One of 1 route, by a classifier");
  });
});

describe("routesOf and allSpecNodes", () => {
  it("lists a router's routes, the default last", () => {
    const reportPath = node("report_path", spec_(router));
    if (reportPath.type !== "router") throw new Error("not a router");
    expect(routesOf(reportPath).map(([id]) => id)).toEqual(["clean", "fix_first", "default"]);
  });

  it("walks the routes and the default in run order", () => {
    expect(allSpecNodes(spec_(router)).map((n) => n.id)).toEqual([
      "main",
      "triage",
      "report_path",
      "clean_report",
      "fix",
      "plan",
      "fix_report",
      "standard_report",
      "summary",
    ]);
  });
});
