import { describe, expect, test } from "vitest";

import { actionInfo, actionsOf, describe as describeEvent, type AuditEvent } from "./actions";
import { auditEvent } from "./testing";

function line(overrides: Partial<AuditEvent>): string {
  return describeEvent(auditEvent(overrides));
}

describe("describe", () => {
  test.each<[string, Partial<AuditEvent>, string]>([
    [
      "a template run with a repo and budget",
      {
        details: {
          template_id: "generate-docs",
          repo_url: "https://github.com/acme/docs",
          budget_usd: "5.00",
        },
      },
      "Started generate-docs on acme/docs · budget $5.00",
    ],
    ["a run of a raw workflow", { details: {} }, "Started a workflow"],
    [
      "a rerun",
      {
        action: "run.rerun",
        details: { rerun_of: "9f8e7d6c-0000-4000-8000-000000000000", budget_usd: null },
      },
      "Rerun of 9f8e7d6c",
    ],
    [
      "a cancel request",
      { action: "run.cancel_requested", details: { status: "waiting" } },
      "Asked to cancel while waiting",
    ],
    [
      "a failed run",
      {
        action: "run.ended",
        actor: { type: "system", id: null },
        details: { status: "failed", failure_reason: "node w: boom", estimated_usd: "0.0420" },
      },
      "Failed · node w: boom · $0.042",
    ],
    [
      "a run that cost nothing",
      { action: "run.ended", details: { status: "completed", estimated_usd: "0E-8" } },
      "Succeeded",
    ],
    [
      "a repo a run created",
      {
        action: "repo.created",
        actor: { type: "system", id: null },
        details: { full_name: "acme/docs-new", private: true },
      },
      "Created the private repo acme/docs-new",
    ],
    [
      "an approval with edits and a comment",
      {
        action: "gate.approved",
        node_id: "approve",
        details: { comment: "looks good", edited_files: 2, edited_paths: ["a.md", "b.md"] },
      },
      "Approved approve with edits to 2 files · “looks good”",
    ],
    [
      "a rejection",
      { action: "gate.rejected", node_id: "approve", details: { comment: null, edited_files: 0 } },
      "Rejected approve",
    ],
    [
      "a Claude key",
      {
        action: "connection.added",
        run_id: null,
        details: { provider: "claude", key_hint: "1234", replaced: true },
      },
      "Replaced Claude key ····1234",
    ],
    [
      "a GitHub disconnect",
      {
        action: "connection.removed",
        run_id: null,
        details: { provider: "github", key_hint: null, account_login: "acme" },
      },
      "Removed GitHub (acme)",
    ],
    [
      "lowered limits and a budget",
      {
        action: "policy.updated",
        details: {
          before: { agents_alive: null, budget_usd: null },
          after: { agents_alive: 4, budget_usd: "10" },
        },
      },
      "agents alive default → 4, budget none → $10.00",
    ],
    [
      "prices",
      {
        action: "pricing.updated",
        details: { added: ["a"], changed: ["b", "c"], removed: [] },
      },
      "added a; changed b, c",
    ],
    [
      "workflow created",
      { action: "workflow.created", details: { workflow_id: "docs", version: 1 } },
      "Created docs v1",
    ],
    [
      "workflow changed",
      {
        action: "workflow.updated",
        details: { workflow_id: "docs", version: 3, base_version: 2, op_count: 4 },
      },
      "Changed docs v3 · 4 edits",
    ],
    [
      "workflow version restored",
      {
        action: "workflow.restored",
        details: { workflow_id: "docs", version: 4, base_version: 3, restored_from: 1 },
      },
      "Restored docs v1 as v4",
    ],
  ])("%s", (_, overrides, expected) => {
    expect(line(overrides)).toBe(expected);
  });

  test("malformed details are ignored, not shown", () => {
    expect(
      line({
        action: "gate.approved",
        node_id: null,
        details: { comment: 42, edited_files: "many", edited_paths: "x" },
      }),
    ).toBe("Approved a gate");
    expect(line({ action: "policy.updated", details: { before: "x", after: [1] } })).toBe(
      "Run limits saved",
    );
    expect(line({ action: "pricing.updated", details: { added: [1, null] } })).toBe("Prices saved");
  });

  test("markup in details stays text", () => {
    expect(
      line({ action: "gate.rejected", node_id: "g", details: { comment: "<img src=x>" } }),
    ).toBe("Rejected g · “<img src=x>”");
  });

  test("an action the page does not know shows its name", () => {
    const unknown = { action: "workflow.published" } as unknown as Partial<AuditEvent>;
    expect(line(unknown)).toBe("workflow.published");
    expect(actionInfo("workflow.published")).toEqual({ label: "workflow.published", icon: null });
  });
});

test("each category has its actions", () => {
  expect(actionsOf("runs")).toEqual([
    "run.created",
    "run.rerun",
    "run.cancel_requested",
    "run.ended",
    "repo.created",
  ]);
  expect(actionsOf("approvals")).toEqual(["gate.approved", "gate.rejected", "gate.expired"]);
  expect(actionsOf("workflows")).toEqual([
    "workflow.created",
    "workflow.updated",
    "workflow.restored",
  ]);
  expect(actionsOf("settings")).toEqual([
    "connection.added",
    "connection.removed",
    "policy.updated",
    "pricing.updated",
  ]);
});
