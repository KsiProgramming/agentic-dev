import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library only unmounts between tests by itself when Vitest globals are on.
afterEach(cleanup);

// Radix popovers (menus, tooltips) measure their trigger; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// The command menu (cmdk) scrolls the active item into view; jsdom has no layout.
Element.prototype.scrollIntoView ??= function () {};
