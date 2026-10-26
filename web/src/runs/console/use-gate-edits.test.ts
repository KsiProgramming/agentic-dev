import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { FileChange } from "../gates";
import { useGateEdits } from "./use-gate-edits";

const PAGE: FileChange = {
  nodeId: "writer",
  path: "docs/a.md",
  oldPath: null,
  status: "added",
  editable: true,
  reason: null,
  before: null,
  after: "# A\n",
};
const LOGO: FileChange = { ...PAGE, path: "logo.png", editable: false, reason: "binary" };
const CHANGES = [PAGE, LOGO];

afterEach(() => vi.restoreAllMocks());

test("an edit is kept until it is discarded", () => {
  const { result } = renderHook(() => useGateEdits(CHANGES));
  expect(result.current.textOf(PAGE)).toBe("# A\n");

  act(() => result.current.edit(PAGE, "# B\n"));

  expect(result.current.count).toBe(1);
  expect(result.current.edits).toEqual([{ nodeId: "writer", path: "docs/a.md", content: "# B\n" }]);
  expect(result.current.isEdited(PAGE)).toBe(true);
  expect(result.current.textOf(PAGE)).toBe("# B\n");

  act(() => result.current.discard(PAGE));

  expect(result.current.count).toBe(0);
  expect(result.current.textOf(PAGE)).toBe("# A\n");
});

test("text equal to the original is no edit, and read-only files take none", () => {
  const { result } = renderHook(() => useGateEdits(CHANGES));

  act(() => result.current.edit(PAGE, "# B\n"));
  act(() => result.current.edit(PAGE, "# A\n"));
  act(() => result.current.edit(LOGO, "not an image"));

  expect(result.current.edits).toEqual([]);
  expect(result.current.isEdited(LOGO)).toBe(false);
});

test("leaving the page asks first only while there are edits", () => {
  const add = vi.spyOn(window, "addEventListener");
  const remove = vi.spyOn(window, "removeEventListener");
  const { result } = renderHook(() => useGateEdits(CHANGES));
  const unload = () => add.mock.calls.filter(([type]) => type === "beforeunload");
  expect(unload()).toEqual([]);

  act(() => result.current.edit(PAGE, "# B\n"));
  const [[, listener]] = unload() as [[string, (e: Event) => void]];
  const event = new Event("beforeunload", { cancelable: true });
  listener(event);
  expect(event.defaultPrevented).toBe(true);

  act(() => result.current.discard(PAGE));
  expect(remove).toHaveBeenCalledWith("beforeunload", listener);
});
