import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import plugin from "./no-raw-colors.mjs";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tester = new RuleTester({
  languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
});

const raw = (code) => ({ code, errors: [{ messageId: "raw" }] });

tester.run("no-raw-colors", plugin.rules["no-raw-colors"], {
  valid: [
    `<div className="bg-background text-muted-foreground border-border" />`,
    `<span className="bg-status-waiting-muted text-status-failed hover:bg-primary/90" />`,
    `<div className="bg-overlay shadow-dock ring-ring/50 outline-ring" />`,
    // Words and ids that only look like colours.
    `const label = "Pull request #123";`,
    "const title = `#${number} red-team notes`;",
    `const help = "Choose a color(s) for the chart";`,
    `const path = "src/to-red/file.ts";`,
    `<div className="text-meta tabular-nums max-w-[72ch]" />`,
  ],
  invalid: [
    raw(`<div className="bg-red-100" />`),
    raw(`<div className="flex text-indigo-600" />`),
    raw(`<div className="hover:border-zinc-200/50" />`),
    raw(`<div className="fixed inset-0 bg-black/10" />`),
    raw("const c = cn(`px-2 ${open ? 'text-white' : ''}`);"),
    raw(`<div className="bg-[#4f46e5]" />`),
    raw(`<div className="text-[oklch(0.5_0.2_270)]" />`),
    raw(`<div className="shadow-[0_-1px_3px_0_rgb(0_0_0/0.06)]" />`),
    raw(`<div className="fill-[color(display-p3_1_0_0)]" />`),
    raw(`<div style={{ color: "#4f46e5" }} />`),
    raw(`const accent = "#fff";`),
    raw(`<div style={{ background: "rgb(0 0 0 / 10%)" }} />`),
    raw(`const ink = "oklch(0.21 0.006 285.885)";`),
  ],
});
