import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { useFollowScroll } from "./use-follow-scroll";

let scrollTo: ReturnType<typeof vi.fn>;
let now: number;

/** Lay the page out as `height` px tall, scrolled to `y`, in a 800 px tall window. */
function page(height: number, y: number) {
  Object.defineProperty(document.documentElement, "scrollHeight", {
    configurable: true,
    value: height,
  });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
}

function scroll(height: number, y: number) {
  page(height, y);
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
}

/** Render a live page, then let the replay of stored events pass. */
function livePage() {
  const hook = renderHook(({ v }) => useFollowScroll(v, true), { initialProps: { v: 1 } });
  now += 2000;
  return hook;
}

beforeEach(() => {
  scrollTo = vi.fn();
  vi.stubGlobal("scrollTo", scrollTo);
  now = 1_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  page(2000, 0);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("the replay of stored events neither scrolls the page nor shows the pill", () => {
  const { rerender, result } = renderHook(({ v }) => useFollowScroll(v, true), {
    initialProps: { v: 1 },
  });
  rerender({ v: 40 });
  expect(scrollTo).not.toHaveBeenCalled();
  expect(result.current.behind).toBe(false);
  expect(result.current.following).toBe(false);
});

test("follows new content once the user is at the bottom", () => {
  const { rerender, result } = livePage();
  scroll(2000, 1200);
  expect(result.current.following).toBe(true);
  rerender({ v: 2 });
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(result.current.behind).toBe(false);
});

test("away from the bottom, new content offers a jump to the latest", () => {
  const { rerender, result } = livePage();
  scroll(2000, 1200);
  scroll(2000, 200);
  rerender({ v: 2 });
  expect(scrollTo).not.toHaveBeenCalled();
  expect(result.current.behind).toBe(true);

  act(() => result.current.jump());
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(result.current.behind).toBe(false);
  expect(result.current.following).toBe(true);
});

test("does nothing for a run that is not live", () => {
  const { rerender, result } = renderHook(({ v }) => useFollowScroll(v, false), {
    initialProps: { v: 1 },
  });
  now += 2000;
  rerender({ v: 2 });
  expect(scrollTo).not.toHaveBeenCalled();
  expect(result.current.behind).toBe(false);
});
