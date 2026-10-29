import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The tokens in globals.css match specs/design-language.md, and every text colour is at least
 * 4.5:1 on every surface it sits on, in light and dark (WCAG 2.2 AA). Read from the CSS itself,
 * so a token change that breaks contrast fails here before axe runs.
 */

const css = readFileSync(resolve(__dirname, "globals.css"), "utf8");

/** The custom properties declared in the first block that starts with `selector {`. */
function block(selector: string): Record<string, string> {
  const start = css.indexOf(`\n${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("\n}", start));
  const vars: Record<string, string> = {};
  for (const match of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) vars[match[1]] = match[2].trim();
  return vars;
}

const light = block(":root");
const dark = { ...light, ...block(".dark") };

function value(theme: Record<string, string>, name: string): string {
  let current = theme[name];
  for (let hops = 0; current?.startsWith("var("); hops++) {
    if (hops > 5) throw new Error(`${name}: var() loop`);
    current = theme[current.slice(4, -1).trim()];
  }
  if (!current) throw new Error(`${name} is not defined`);
  return current;
}

/** oklch(L C H) → relative luminance (sRGB, WCAG). */
function luminance(oklch: string): number {
  const match = /^oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)$/.exec(oklch);
  if (!match) throw new Error(`not an opaque oklch(): ${oklch}`);
  const [L, C, H] = match.slice(1).map(Number);
  const a = C * Math.cos((H * Math.PI) / 180);
  const b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  const r = clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s);
  const g = clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s);
  const bl = clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s);
  return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
}

function contrast(theme: Record<string, string>, text: string, surface: string): number {
  const [x, y] = [luminance(value(theme, text)), luminance(value(theme, surface))];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

const TEXT = ["--foreground", "--foreground-secondary", "--muted-foreground", "--placeholder"];
const SURFACES = ["--background", "--card", "--surface-subtle", "--surface-sunken", "--muted"];
const STATUSES = ["queued", "running", "waiting", "succeeded", "failed", "cancelled"];

describe.each([
  ["light", light],
  ["dark", dark],
])("%s tokens", (_, theme) => {
  it.each(TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface])))(
    "%s is ≥ 4.5:1 on %s",
    (text, surface) => {
      expect(contrast(theme, text, surface)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(STATUSES)("status %s is ≥ 4.5:1 on its fill and on the background", (status) => {
    expect(
      contrast(theme, `--status-${status}`, `--status-${status}-muted`),
    ).toBeGreaterThanOrEqual(4.5);
    expect(contrast(theme, `--status-${status}`, "--background")).toBeGreaterThanOrEqual(4.5);
    expect(value(theme, `--status-${status}-border`)).toBeTruthy();
  });

  it.each(["critical", "high", "medium", "low", "info"])(
    "severity %s is ≥ 4.5:1 on its fill and on the background",
    (severity) => {
      expect(
        contrast(theme, `--severity-${severity}`, `--severity-${severity}-muted`),
      ).toBeGreaterThanOrEqual(4.5);
      expect(contrast(theme, `--severity-${severity}`, "--background")).toBeGreaterThanOrEqual(4.5);
      expect(value(theme, `--severity-${severity}-border`)).toBeTruthy();
    },
  );

  it("primary text is ≥ 4.5:1 on primary", () => {
    expect(contrast(theme, "--primary-foreground", "--primary")).toBeGreaterThanOrEqual(4.5);
  });
});

it("the primary is ink, not a hue", () => {
  expect(value(light, "--primary")).toBe("oklch(0.21 0.006 285.9)");
  expect(value(dark, "--primary")).toBe("oklch(0.985 0 0)");
  expect(value(light, "--ring")).toBe(value(light, "--primary"));
});

it("every new token has a utility in @theme", () => {
  for (const name of [
    "foreground-secondary",
    "placeholder",
    "surface-sunken",
    "surface-subtle",
    "border-strong",
    "divider",
    ...STATUSES.map((status) => `status-${status}-border`),
  ]) {
    expect(css).toContain(`--color-${name}: var(--${name});`);
  }
});
