# Validation: UI v2 foundations

## Done when (from roadmap)
> Every page renders times, durations, costs and ids through the shared components; `pnpm lint` fails on `bg-red-100` or `#4f46e5` in a component; layout screenshots at 375, 768 and 1440 px pass

## Automated checks
- [ ] Vitest: one test file per display component (`relative-time`, `duration`, `money`, `token-count`, `id-chip`, `stat-tile`): text, `<time dateTime>`, tooltip content, `tabular-nums`, copy on click (`IdChip`), unpriced cost shows "—" with its caveat.
- [ ] Vitest: formatters honour a passed locale and time zone (e.g. `de-DE` / `Europe/Berlin` gives 24-hour and `,` decimals).
- [ ] Vitest: `no-raw-colors` `RuleTester` rejects `bg-red-100`, `text-indigo-600`, `bg-[#4f46e5]`, `"#4f46e5"`, `text-[oklch(…)]` and accepts semantic token classes.
- [ ] `rg "toLocale(String|TimeString|DateString)\(" web/src --glob '!**/*.test.*'` finds nothing outside the formatter module.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test` green.
- [ ] `pnpm test:e2e` green, including `layout.spec.ts` (375, 768, 1440 px, no horizontal scroll, updated baselines) and `a11y.spec.ts` (no serious axe issues) in light and dark.
- [ ] CI green on the PR.

## Manual / demo checks
- [ ] Add `className="bg-red-100"` to any component and run `pnpm lint`: it fails naming the rule; same for `style={{ color: "#4f46e5" }}`. Revert.
- [ ] Look at Runs, a run console (finished and waiting), Templates, Settings and Audit at 375 and 1440 px, in light and dark: pages use the full width, text blocks stay readable, no horizontal page scroll.
- [ ] Hover a time: exact time in the tooltip. Click an `IdChip`: full id copied, toast shown. Toggle compact mode: table rows go 40 → 32 px and the choice survives reload.
- [ ] Switch the browser locale to German: dates are 24-hour and numbers use German separators.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/tech-stack.md` updated (Foundations moved out of "UI v2", decisions log) and `CLAUDE.md` rule 3 names the components, in the same PR
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`
- [ ] No rule from `CLAUDE.md` broken, or the break stated in the PR and the spec updated
