import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppShell } from "./app-shell";

const nav = vi.hoisted(() => ({ pathname: "/runs" }));

vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "system", setTheme: vi.fn() }) }));

beforeEach(() => {
  nav.pathname = "/runs";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json([{ id: "w1", name: "Default", created_at: "" }])),
  );
});

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
