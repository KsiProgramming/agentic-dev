import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { DensityToggle } from "./density-toggle";

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("compact");
});

test("compact mode is a pressed toggle kept in this browser", () => {
  render(<DensityToggle />);
  const toggle = screen.getByRole("button", { name: "Compact rows" });
  expect(toggle.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(toggle);

  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  expect(document.documentElement.classList.contains("compact")).toBe(true);
  expect(localStorage.getItem("density")).toBe("compact");

  fireEvent.click(toggle);

  expect(document.documentElement.classList.contains("compact")).toBe(false);
  expect(localStorage.getItem("density")).toBe("comfortable");
});

test("a stored choice is applied on load", () => {
  localStorage.setItem("density", "compact");
  render(<DensityToggle />);

  expect(screen.getByRole("button", { name: "Compact rows" }).getAttribute("aria-pressed")).toBe(
    "true",
  );
  expect(document.documentElement.classList.contains("compact")).toBe(true);
});
