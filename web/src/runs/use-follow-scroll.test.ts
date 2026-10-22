import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { useFollowScroll } from "./use-follow-scroll";

let scrollTo: ReturnType<typeof vi.fn>;

/** Lay the page out as `height` px tall, scrolled to `y`, in a 800 px tall window. */
function page(height: number, y: number) {
  Object.defineProperty(document.documentElement, "scrollHeight", {
    configurable: true,
    value: height,
  });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
}

beforeEach(() => {
  scrollTo = vi.fn();
  vi.stubGlobal("scrollTo", scrollTo);
  page(2000, 1200);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("follows new content while the user is at the bottom", () => {
  const { rerender, result } = renderHook(({ v }) => useFollowScroll(v, true), {
    initialProps: { v: 1 },
  });
  scrollTo.mockClear();
  rerender({ v: 2 });
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(result.current.behind).toBe(false);
});

test("stops following once scrolled up, and offers a jump to the latest", () => {
  const { rerender, result } = renderHook(({ v }) => useFollowScroll(v, true), {
    initialProps: { v: 1 },
  });
  page(2000, 200);
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
  scrollTo.mockClear();
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
  scrollTo.mockClear();
  rerender({ v: 2 });
  expect(scrollTo).not.toHaveBeenCalled();
  expect(result.current.behind).toBe(false);
});
