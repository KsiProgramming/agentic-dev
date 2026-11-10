import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  manifestByKey,
  ManifestIcon,
  paletteGroups,
  paletteKey,
  type NodeManifest,
} from "./node-types";

const manifest = (kind: string, category: string) =>
  ({ kind, label: kind, category }) as unknown as NodeManifest;

describe("node types", () => {
  it("groups the palette by category in a fixed order, an unknown one last", () => {
    const groups = paletteGroups([
      manifest("reduce", "combine"),
      manifest("agent", "step"),
      manifest("odd", "custom"),
      manifest("loop", "flow"),
      manifest("gate", "step"),
    ]);
    expect(groups.map((g) => [g.label, g.items.map((m) => m.kind)])).toEqual([
      ["Steps", ["agent", "gate"]],
      ["Flow", ["loop"]],
      ["Combine", ["reduce"]],
      ["Other", ["odd"]],
    ]);
  });

  it("draws an icon this app does not have as a box", () => {
    const { container } = render(<ManifestIcon name="megaphone" />);
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("lucide-box");
  });
});

describe("workspace composites (6.6)", () => {
  const composite = {
    ...manifest("subflow", "workspace"),
    label: "Security review",
    composite: { workflow_id: "security-review", version: 3 },
  } as unknown as NodeManifest;

  it("lists composites last, under Workspace nodes", () => {
    const groups = paletteGroups([
      composite,
      manifest("subflow", "flow"),
      manifest("agent", "step"),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Steps", "Flow", "Workspace nodes"]);
  });

  it("names a composite's entry apart from the subflow primitive it shares a kind with", () => {
    const subflow = manifest("subflow", "flow");
    expect([paletteKey(subflow), paletteKey(composite)]).toEqual([
      "subflow",
      "composite:security-review",
    ]);
    expect(manifestByKey([subflow, composite], "composite:security-review")).toBe(composite);
    expect(manifestByKey([subflow, composite], "subflow")).toBe(subflow);
  });
});
