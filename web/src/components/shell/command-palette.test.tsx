import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render as renderUi, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { FakeEventSource, runSummary } from "@/runs/testing";
import type { RunSummary } from "@/runs/summaries";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { AppShell } from "./app-shell";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/runs",
  useRouter: () => ({ push: nav.push }),
}));

const theme = vi.hoisted(() => ({ resolved: "light", setTheme: vi.fn() }));
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", resolvedTheme: theme.resolved, setTheme: theme.setTheme }),
}));

const ID = "1a2b3c4d-5e6f-4a1b-8c2d-0123456789ab";
const docs = runSummary({
  id: ID,
  workflow: { id: "docs", name: "Generate docs" },
  pr_url: "https://github.com/acme/docs/pull/42",
});

const api = vi.hoisted(() => ({
  search: (() => []) as (q: string) => RunSummary[] | Response,
  waiting: [] as RunSummary[],
  queries: [] as string[],
}));

beforeEach(() => {
  nav.push.mockReset();
  theme.resolved = "light";
  theme.setTheme.mockReset();
  api.search = () => [];
  api.waiting = [];
  api.queries = [];
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const url = new URL(request.url);
      if (url.pathname !== "/runs") {
        return Response.json([{ id: DEFAULT_WORKSPACE_ID, name: "Default", created_at: "" }]);
      }
      const q = url.searchParams.get("q");
      if (q === null) return Response.json({ items: api.waiting, next_cursor: null });
      api.queries.push(q);
      const found = api.search(q);
      return found instanceof Response ? found : Response.json({ items: found, next_cursor: null });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderUi(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function press(key: string, init: KeyboardEventInit = {}, target: Document | Element = document) {
  fireEvent.keyDown(target, { key, ...init });
}

async function openPalette() {
  press("k", { ctrlKey: true });
  return screen.findByRole("dialog", { name: "Command palette" });
}

function type(dialog: HTMLElement, text: string) {
  fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: text } });
}

test("Done when (11.7): ⌘K opens a run from its short id", async () => {
  api.search = (q) => (ID.startsWith(q) ? [docs] : []);
  render(<AppShell>page</AppShell>);

  press("k", { metaKey: true });
  const dialog = await screen.findByRole("dialog", { name: "Command palette" });
  type(dialog, "1a2b3c4d");
  const row = await within(dialog).findByRole("option", { name: /Generate docs/ });
  expect(row.textContent).toContain("1a2b3c4d");
  expect(row.textContent).toContain("#42");
  fireEvent.click(row);

  expect(nav.push).toHaveBeenCalledWith(`/runs/${ID}`);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(api.queries).toEqual(["1a2b3c4d"]);
});

test("Ctrl+K and the top-bar button open it; Ctrl+K again closes it", async () => {
  render(<AppShell>page</AppShell>);

  fireEvent.click(screen.getByRole("button", { name: "Search runs and commands" }));
  expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeDefined();

  press("k", { ctrlKey: true });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await openPalette();
});

test("the shortcut works from a page field but not inside the diff editor", async () => {
  render(
    <AppShell>
      <input aria-label="Page field" />
      <div className="monaco-editor">
        <textarea aria-label="Editor" />
      </div>
    </AppShell>,
  );

  press("k", { ctrlKey: true }, screen.getByLabelText("Editor"));
  expect(screen.queryByRole("dialog")).toBeNull();

  press("k", { ctrlKey: true }, screen.getByLabelText("Page field"));
  expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeDefined();
});

test("#42 finds a run by its pull request", async () => {
  api.search = (q) => (q === "#42" ? [docs] : []);
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  type(dialog, "#42");

  expect(await within(dialog).findByRole("option", { name: /Generate docs/ })).toBeDefined();
});

test("a full id the search does not find still opens its run", async () => {
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  type(dialog, ID.toUpperCase());
  fireEvent.click(await within(dialog).findByRole("option", { name: /Open run 1a2b3c4d/ }));

  expect(nav.push).toHaveBeenCalledWith(`/runs/${ID}`);
});

test("nothing found says so; a failed search can be retried", async () => {
  let fail = true;
  api.search = () => (fail ? Response.json({ detail: "boom" }, { status: 500 }) : [docs]);
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  type(dialog, "gen");
  const retry = await within(dialog).findByRole("option", { name: /Could not search runs/ });
  fail = false;
  fireEvent.click(retry);
  expect(await within(dialog).findByRole("option", { name: /Generate docs/ })).toBeDefined();

  api.search = () => [];
  type(dialog, "zzz");
  expect(await within(dialog).findByText("Nothing matches “zzz”.")).toBeDefined();
});

test("Approve opens the oldest waiting gate in the Inbox", async () => {
  api.waiting = [
    runSummary({
      id: "newer",
      status: "waiting",
      created_at: "2026-10-27T10:00:00Z",
      waiting_gate: { node_id: "g", title: "Approve the PR" },
    }),
    runSummary({
      id: "older",
      status: "waiting",
      created_at: "2026-10-26T10:00:00Z",
      waiting_gate: { node_id: "g", title: "Approve the notes" },
    }),
  ];
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  fireEvent.click(
    await within(dialog).findByRole("option", { name: /Approve: Approve the notes/ }),
  );

  expect(nav.push).toHaveBeenCalledWith("/inbox?run=older");
});

test("the theme is toggled from the palette", async () => {
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  fireEvent.click(within(dialog).getByRole("option", { name: "Switch to dark theme" }));

  expect(theme.setTheme).toHaveBeenCalledWith("dark");
});

test("commands and pages are filtered by what is typed; New run opens its sheet", async () => {
  render(<AppShell>page</AppShell>);
  const dialog = await openPalette();

  type(dialog, "limit");
  await waitFor(() =>
    expect(
      within(dialog)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Settings: Limits and budgets"]),
  );

  type(dialog, "new");
  fireEvent.click(await within(dialog).findByRole("option", { name: "New run" }));
  expect(nav.push).toHaveBeenCalledWith("/runs?new=1");
});
