import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { UserMenu } from "./user-menu";

const theme = vi.hoisted(() => ({ current: "system", setTheme: vi.fn() }));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: theme.current, setTheme: theme.setTheme }),
}));

beforeEach(() => {
  theme.current = "system";
  theme.setTheme.mockClear();
});

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("compact");
});

function openMenu() {
  fireEvent.keyDown(screen.getByRole("button", { name: "Preferences" }), { key: "Enter" });
}

test("lists the themes and densities with the current ones checked", () => {
  render(<UserMenu />);
  openMenu();

  const items = screen.getAllByRole("menuitemradio");
  expect(items.map((item) => item.textContent)).toEqual([
    "Light",
    "Dark",
    "System",
    "Comfortable",
    "Compact",
  ]);
  for (const [name, checked] of [
    ["System", "true"],
    ["Dark", "false"],
    ["Comfortable", "true"],
    ["Compact", "false"],
  ]) {
    expect(screen.getByRole("menuitemradio", { name }).getAttribute("aria-checked")).toBe(checked);
  }
});

test.each(["Light", "Dark", "System"])("choosing %s sets that theme", (label) => {
  theme.current = label === "System" ? "dark" : "system";
  render(<UserMenu />);
  openMenu();

  fireEvent.click(screen.getByRole("menuitemradio", { name: label }));

  expect(theme.setTheme).toHaveBeenCalledWith(label.toLowerCase());
});

test("compact rows are chosen in the menu and kept in this browser", () => {
  render(<UserMenu />);
  openMenu();
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Compact" }));

  expect(document.documentElement.classList.contains("compact")).toBe(true);
  expect(localStorage.getItem("density")).toBe("compact");

  openMenu();
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Comfortable" }));

  expect(document.documentElement.classList.contains("compact")).toBe(false);
  expect(localStorage.getItem("density")).toBe("comfortable");
});

test("a stored density is applied on load", () => {
  localStorage.setItem("density", "compact");
  render(<UserMenu />);

  expect(document.documentElement.classList.contains("compact")).toBe(true);
  openMenu();
  expect(screen.getByRole("menuitemradio", { name: "Compact" }).getAttribute("aria-checked")).toBe(
    "true",
  );
});
