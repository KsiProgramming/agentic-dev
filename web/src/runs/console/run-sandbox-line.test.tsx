import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API, json, renderWithQueries, requested, stubApi } from "@/testing/api";

import type { SavedBranchChanges } from "../use-run-changes";
import { RunSandboxLine } from "./run-sandbox-line";

const RUN = "run-1";
const CHANGES = `GET /runs/${RUN}/changes`;
const IN_A_DAY = new Date(Date.now() + 23.5 * 3600 * 1000).toISOString();

afterEach(() => {
  vi.unstubAllGlobals();
});

function branch(
  key: string,
  kind: SavedBranchChanges["kind"],
  paths: string[],
  more: Partial<SavedBranchChanges> = {},
): SavedBranchChanges {
  return {
    node_id: key.split(".")[0] ?? key,
    key,
    branch: `${kind === "wip" ? "wip" : "agent"}/${RUN}/${key}`,
    kind,
    version: 1,
    head: "1".repeat(40),
    commits: kind === "wip" ? 2 : 1,
    saved_at: "2026-11-15T10:00:00Z",
    changes: paths.map((path) => ({
      node_id: key,
      path,
      old_path: null,
      status: "added",
      editable: true,
      reason: null,
      before: null,
      after: `${path}\n`,
      protected: false,
      rule: null,
    })),
    changes_error: null,
    bundle_removed_at: null,
    ...more,
  };
}

function kept(until = IN_A_DAY) {
  return { state: "kept" as const, kept_until: until, removed_at: null };
}

function show(sandbox: Parameters<typeof RunSandboxLine>[0]["sandbox"]) {
  return renderWithQueries(<RunSandboxLine runId={RUN} sandbox={sandbox} baseUrl={API} />);
}

describe("a failed or cancelled run's sandbox (12.3)", () => {
  it("says until when it is kept", () => {
    show(kept());

    const line = screen.getByTestId("run-sandbox");
    expect(line.dataset.state).toBe("kept");
    expect(within(line).getByText("Sandbox kept")).toBeTruthy();
    expect(within(line).getByText("Expires in 23 h")).toBeTruthy();
    expect(within(line).getByRole("button", { name: "Remove sandbox now" })).toBeTruthy();
  });

  it("says when it was removed, and still offers what the writers changed", () => {
    show({ state: "removed", kept_until: IN_A_DAY, removed_at: "2026-11-15T10:00:00Z" });

    const line = screen.getByTestId("run-sandbox");
    expect(within(line).getByText("Sandbox removed")).toBeTruthy();
    expect(within(line).getByText(/what the writers changed is still saved/)).toBeTruthy();
    expect(within(line).getByRole("button", { name: "View changes" })).toBeTruthy();
    expect(within(line).queryByRole("button", { name: "Remove sandbox now" })).toBeNull();
  });

  it("is not shown while the run works, nor for a run with no sandbox left to speak of", () => {
    const { container } = show({ state: "running", kept_until: null, removed_at: null });
    expect(container.textContent).toBe("");
    show({ state: "none", kept_until: null, removed_at: null });
    expect(screen.queryByTestId("run-sandbox")).toBeNull();
  });

  it("is removed only after confirming, and then reads as being removed", async () => {
    let removed = false;
    const fetch = stubApi({
      [`DELETE /runs/${RUN}/sandbox`]: () => {
        removed = true;
        return json(202, { state: "kept", kept_until: new Date().toISOString(), removed_at: null });
      },
    });
    show(kept());

    fireEvent.click(screen.getByRole("button", { name: "Remove sandbox now" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(removed).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove sandbox" }));

    await waitFor(() => expect(requested(fetch)).toEqual([`DELETE /runs/${RUN}/sandbox`]));
    expect(await screen.findByRole("button", { name: "Removing…" })).toBeTruthy();
  });

  it("reads as being removed once its time is up", () => {
    show(kept(new Date(Date.now() - 1000).toISOString()));

    expect(screen.getByText("Sandbox being removed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove sandbox now" })).toBeNull();
  });
});

describe("what the writers changed (12.3)", () => {
  it("shows one writer at a time, its uncommitted work in place of its branch", async () => {
    stubApi({
      [CHANGES]: () =>
        json(200, [
          branch("fix", "integration", ["a.py"]),
          branch("writer", "writer", ["NOTES.md"]),
          branch("writer", "wip", ["NOTES.md", "DRAFT.md"]),
        ]),
    });
    show(kept());

    fireEvent.click(screen.getByRole("button", { name: "View changes" }));

    const sheet = await screen.findByTestId("gate-review");
    const picker = await within(sheet).findByLabelText("Writer");
    const options = within(picker)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["fix · integration branch", "writer · includes uncommitted work"]);
    expect(within(sheet).getAllByText("a.py")).not.toHaveLength(0);

    fireEvent.change(picker, { target: { value: "wip:writer" } });

    expect(await within(sheet).findAllByText("DRAFT.md")).not.toHaveLength(0);
    expect(
      within(sheet).getByText("As it was on disk when the run ended, uncommitted work included"),
    ).toBeTruthy();
  });

  it("are still shown once the saved commits are gone", async () => {
    stubApi({
      [CHANGES]: () =>
        json(200, [
          branch("writer", "writer", ["NOTES.md"], { bundle_removed_at: "2026-11-15T10:00:00Z" }),
        ]),
    });
    show({ state: "removed", kept_until: IN_A_DAY, removed_at: "2026-11-15T10:00:00Z" });

    fireEvent.click(screen.getByRole("button", { name: "View changes" }));

    const sheet = await screen.findByTestId("gate-review");
    expect(await within(sheet).findAllByText("NOTES.md")).not.toHaveLength(0);
    expect(within(sheet).getByText(/Its saved commits were removed/)).toBeTruthy();
  });

  it("say so when no writer changed a file", async () => {
    stubApi({ [CHANGES]: () => json(200, []) });
    show(kept());

    fireEvent.click(screen.getByRole("button", { name: "View changes" }));

    expect(await screen.findByText("No writer changed a file.")).toBeTruthy();
  });

  it("can be tried again when they cannot be loaded", async () => {
    let calls = 0;
    stubApi({
      [CHANGES]: () => {
        calls += 1;
        return calls === 1 ? json(500, {}) : json(200, [branch("writer", "writer", ["A.md"])]);
      },
    });
    show(kept());

    fireEvent.click(screen.getByRole("button", { name: "View changes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    const sheet = await screen.findByTestId("gate-review");
    expect(await within(sheet).findAllByText("A.md")).not.toHaveLength(0);
  });
});
