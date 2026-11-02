import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ManifestIcon, paletteGroups, type NodeManifest } from "./node-types";

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
