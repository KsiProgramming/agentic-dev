/**
 * What React Flow needs from the browser and jsdom lacks (reactflow.dev → Testing): a
 * `ResizeObserver` that reports, `DOMMatrixReadOnly`, and element sizes taken from inline styles.
 * Call once per test file, before rendering a graph.
 */

class ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    // React Flow reads the size from `contentRect` (since @xyflow/react 12.10).
    const contentRect = { width: 1024, height: 768 } as DOMRectReadOnly;
    setTimeout(() => this.callback([{ target, contentRect } as ResizeObserverEntry], this), 0);
  }

  unobserve() {}

  disconnect() {}
}

class DOMMatrixReadOnly {
  m22: number;

  constructor(transform: string) {
    const scale = transform?.match(/scale\(([1-9.])\)/)?.[1];
    this.m22 = scale !== undefined ? +scale : 1;
  }
}

let installed = false;

export function mockReactFlow() {
  if (installed) return;
  installed = true;
  globalThis.ResizeObserver = ResizeObserver;
  // @ts-expect-error: only what React Flow reads.
  globalThis.DOMMatrixReadOnly = DOMMatrixReadOnly;
  Object.defineProperties(HTMLElement.prototype, {
    offsetHeight: {
      get(this: HTMLElement) {
        return parseFloat(this.style.height) || 1;
      },
    },
    offsetWidth: {
      get(this: HTMLElement) {
        return parseFloat(this.style.width) || 1;
      },
    },
  });
  (SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox = () =>
    ({ x: 0, y: 0, width: 0, height: 0 }) as DOMRect;
}
