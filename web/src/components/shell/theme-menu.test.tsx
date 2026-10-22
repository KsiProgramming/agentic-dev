import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { ThemeMenu } from "./theme-menu";

const theme = vi.hoisted(() => ({ current: "system", setTheme: vi.fn() }));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: theme.current, setTheme: theme.setTheme }),
}));

beforeEach(() => {
  theme.current = "system";
  theme.setTheme.mockClear();
});

function openMenu() {
  fireEvent.keyDown(screen.getByRole("button", { name: "Theme" }), { key: "Enter" });
}

test("lists light, dark and system with the current one checked", () => {
  render(<ThemeMenu />);
  openMenu();

  const items = screen.getAllByRole("menuitemradio");
  expect(items.map((item) => item.textContent)).toEqual(["Light", "Dark", "System"]);
  expect(screen.getByRole("menuitemradio", { name: "System" }).getAttribute("aria-checked")).toBe(
    "true",
  );
  expect(screen.getByRole("menuitemradio", { name: "Dark" }).getAttribute("aria-checked")).toBe(
    "false",
  );
});

test.each(["Light", "Dark", "System"])("choosing %s sets that theme", (label) => {
  theme.current = label === "System" ? "dark" : "system";
  render(<ThemeMenu />);
  openMenu();

  fireEvent.click(screen.getByRole("menuitemradio", { name: label }));

  expect(theme.setTheme).toHaveBeenCalledWith(label.toLowerCase());
});
