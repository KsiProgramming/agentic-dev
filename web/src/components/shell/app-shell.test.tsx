import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render as renderUi,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { FakeEventSource, runSummary } from "@/runs/testing";
import { DEFAULT_WORKSPACE_ID, WORKSPACE_COOKIE } from "@/workspace";

import { AppShell } from "./app-shell";

const nav = vi.hoisted(() => ({ pathname: "/runs" }));

vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "system", setTheme: vi.fn() }) }));

const api = vi.hoisted(() => ({ waiting: [] as unknown[] }));

beforeEach(() => {
  nav.pathname = "/runs";
  api.waiting = [];
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) =>
      new URL(request.url).pathname === "/runs"
        ? Response.json({ items: api.waiting, next_cursor: null })
        : Response.json([{ id: DEFAULT_WORKSPACE_ID, name: "Default", created_at: "" }]),
    ),
  );
});

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderUi(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

function sidebar() {
  return within(screen.getByRole("complementary", { name: "Sidebar" }));
}

test("renders the page inside the main landmark with a skip link to it", () => {
  render(<AppShell>page body</AppShell>);

  expect(screen.getByRole("main").textContent).toBe("page body");
  expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href")).toBe(
    "#content",
  );
  expect(screen.getByRole("main").id).toBe("content");
});

test("marks the current section in the nav", () => {
  nav.pathname = "/runs/1a2b3c4d-0000-0000-0000-000000000000";
  render(<AppShell>page</AppShell>);

  expect(sidebar().getByRole("link", { name: "Runs" }).getAttribute("aria-current")).toBe("page");
  expect(sidebar().getByRole("link", { name: "Settings" }).getAttribute("aria-current")).toBeNull();
  const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" }));
  expect(crumbs.getByRole("link", { name: "Runs" }).getAttribute("href")).toBe("/runs");
  expect(crumbs.getByText("1a2b3c4d").getAttribute("aria-current")).toBe("page");
});

test("shows the workspace name", async () => {
  render(<AppShell>page</AppShell>);

  expect((await sidebar().findByTestId("workspace-name")).textContent).toBe("Default");
});

test("the drawer opens from the menu button and Escape closes it, focus back on the button", async () => {
  render(<AppShell>page</AppShell>);
  const button = screen.getByRole("button", { name: "Open navigation" });

  fireEvent.click(button);
  const drawer = await screen.findByRole("dialog", { name: "Navigation" });
  expect(within(drawer).getByRole("link", { name: "Templates" })).toBeDefined();

  fireEvent.keyDown(drawer, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(button);
});

test("following a link closes the drawer", async () => {
  render(<AppShell>page</AppShell>);
  fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  const drawer = await screen.findByRole("dialog", { name: "Navigation" });

  fireEvent.click(within(drawer).getByRole("link", { name: "Settings" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("runs waiting at a gate are counted on Runs, the menu button and the page title", async () => {
  api.waiting = [
    runSummary({ id: "r1", status: "waiting" }),
    runSummary({ id: "r2", status: "waiting" }),
  ];
  document.title = "Settings · Agentic Dev";
  render(<AppShell>page</AppShell>);

  const runs = sidebar().getByRole("link", { name: /Runs/ });
  await waitFor(() => expect(runs.textContent).toContain("2 need approval"));
  expect(
    screen.getByRole("button", { name: "Open navigation (2 runs need approval)" }),
  ).toBeDefined();
  await waitFor(() => expect(document.title).toBe("(2) ● Needs approval · Settings · Agentic Dev"));

  // Next.js sets the title of the next page: the count is put back in front.
  act(() => {
    document.title = "Templates · Agentic Dev";
  });
  await waitFor(() =>
    expect(document.title).toBe("(2) ● Needs approval · Templates · Agentic Dev"),
  );
});

test("a gate past its time to live is not counted, even before its run is cancelled", async () => {
  api.waiting = [
    runSummary({
      id: "r1",
      status: "waiting",
      waiting_gate: { node_id: "g", title: "Go?", expires_at: "2000-01-01T00:00:00Z" },
    }),
    runSummary({
      id: "r2",
      status: "waiting",
      waiting_gate: { node_id: "g", title: "Go?", expires_at: "2999-01-01T00:00:00Z" },
    }),
  ];
  render(<AppShell>page</AppShell>);

  const runs = sidebar().getByRole("link", { name: /Runs/ });
  await waitFor(() => expect(runs.textContent).toContain("1 needs approval"));
});

test("with nothing waiting, Runs has no badge and the title is left alone", async () => {
  document.title = "Runs · Agentic Dev";
  render(<AppShell>page</AppShell>);

  await sidebar().findByTestId("workspace-name");
  expect(sidebar().queryByTestId("runs-waiting-badge")).toBeNull();
  expect(document.title).toBe("Runs · Agentic Dev");
});

test("the workspace named by the browser's cookie is the one shown", async () => {
  const other = "00000000-0000-0000-0000-0000000000e2";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json([
        { id: DEFAULT_WORKSPACE_ID, name: "Default", created_at: "" },
        { id: other, name: "E2E", created_at: "" },
      ]),
    ),
  );
  document.cookie = `${WORKSPACE_COOKIE}=${other}`;
  try {
    render(<AppShell>page</AppShell>);

    expect((await sidebar().findByTestId("workspace-name")).textContent).toBe("E2E");
  } finally {
    document.cookie = `${WORKSPACE_COOKIE}=; max-age=0`;
  }
});
