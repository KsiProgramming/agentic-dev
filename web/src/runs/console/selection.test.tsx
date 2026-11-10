import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { auditFixRun, auditFixWaiting } from "../fixtures/audit-fix-run";
import { pendingGate, type PendingGate } from "../gates";
import { specParents } from "../spec-parents";
import { buildTimeline } from "../timeline";
import { ApprovalDock } from "./approval-dock";
import { choiceItems } from "./selection-checklist";
import { stepOutline } from "./step-entries";

const FINDINGS = JSON.stringify(auditFixRun.artifacts["findings.json"]);

function selectionGate(): PendingGate {
  const gate = pendingGate(auditFixWaiting);
  if (!gate) throw new Error("the fixture pauses at the selection gate");
  return gate;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** The approvals posted. */
const posted: unknown[] = [];

/** Answers the artifact the checklist reads, and records approvals. */
function api() {
  vi.stubGlobal(
    "fetch",
    vi.fn<(r: Request) => Promise<Response>>(async (request) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/artifacts/findings.json")) {
        return json({
          name: "findings.json",
          version: 1,
          node_id: "merge",
          media_type: "application/json",
          size: FINDINGS.length,
          created_at: "2026-11-10T12:00:00Z",
          content: FINDINGS,
        });
      }
      if (url.pathname.endsWith("/approvals") && request.method === "POST") {
        const body = (await request.json()) as Record<string, unknown>;
        posted.push(body);
        return json({ run_id: "r", node_id: body.node_id, decision: body.decision }, 202);
      }
      throw new Error(`unexpected ${request.method} ${request.url}`);
    }),
  );
}

function showDock() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ApprovalDock runId="r" gate={selectionGate()} baseUrl="http://api.test" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  posted.length = 0;
  api();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a selection gate (6.7)", () => {
  it("is read from its gate_waiting, with the keys to choose and those checked", () => {
    const gate = selectionGate();
    expect(gate.nodeId).toBe("select_fixes");
    expect(gate.onReject).toBe("end");
    expect(gate.select).toMatchObject({
      artifact: "findings.json",
      items: "findings",
      key: "fingerprint",
      keys: ["b", "c", "a"],
      preselected: ["b", "c"],
      min: 1,
    });
  });

  it("lists the artifact's items as findings, each choosable by its key", () => {
    const items = choiceItems(selectionGate().select!, FINDINGS);
    expect(items?.map((i) => [i.key, i.finding?.severity])).toEqual([
      ["b", "critical"],
      ["c", "high"],
      ["a", "low"],
    ]);
    expect(choiceItems(selectionGate().select!, "not json")).toBeNull();
    expect(choiceItems(selectionGate().select!, '{"findings": 3}')).toBeNull();
  });

  it("items with no key, or a key seen before, cannot be chosen", () => {
    const select = { ...selectionGate().select!, items: "rows", keys: ["x"] };
    const items = choiceItems(
      select,
      JSON.stringify({ rows: [{ fingerprint: "x" }, {}, { fingerprint: "x" }] }),
    );
    expect(items?.map((i) => i.key)).toEqual(["x", null, null]);
  });

  it("the dock opens the checklist instead of approving, and A does too", async () => {
    showDock();
    const dock = screen.getByTestId("approval-dock");
    expect(within(dock).queryByRole("button", { name: /^Approve/ })).toBeNull();
    expect(within(dock).getByRole("button", { name: /End run here/ })).toBeTruthy();

    fireEvent.keyDown(document.body, { key: "a" });

    const sheet = await screen.findByTestId("gate-selection");
    const rows = await within(sheet).findAllByTestId("selection-item");
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.hasAttribute("data-selected"))).toEqual([true, true, false]);
    expect(within(sheet).getByText("2 of 3 selected")).toBeTruthy();
    expect(posted).toEqual([]);
  });

  it("approves with the items chosen, and not with fewer than its minimum", async () => {
    showDock();
    fireEvent.click(screen.getByRole("button", { name: /Choose findings/ }));
    const sheet = await screen.findByTestId("gate-selection");
    await within(sheet).findAllByTestId("selection-item");

    fireEvent.click(within(sheet).getByRole("button", { name: "Clear" }));
    const approve = within(sheet).getByRole("button", { name: "Approve with 0 selected" });
    expect(approve.hasAttribute("disabled")).toBe(true);
    expect(approve.getAttribute("title")).toBe("Select at least 1 item.");

    const boxes = within(sheet).getAllByRole("checkbox");
    fireEvent.click(boxes[2]!);
    fireEvent.click(boxes[0]!);
    fireEvent.click(within(sheet).getByRole("button", { name: "Approve with 2 selected" }));

    await waitFor(() => expect(posted).toHaveLength(1));
    // In the gate's item order, whatever order they were checked in.
    expect(posted[0]).toEqual({
      node_id: "select_fixes",
      decision: "approve",
      selection: ["b", "a"],
    });
  });

  it("the decided gate reads what was chosen, in the step list", () => {
    const parents = specParents(auditFixRun.spec.root);
    const { steps } = buildTimeline(auditFixRun.events, parents);
    const select = steps.find((s) => s.id === "select_fixes")!;
    expect(stepOutline(select)).toBe("Selected 2 of 3 findings");
    expect(stepOutline(steps.find((s) => s.id === "approve_pr")!)).toBe("Approved");
  });
});
