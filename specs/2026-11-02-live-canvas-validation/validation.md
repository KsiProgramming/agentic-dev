# Validation: Live validation on canvas

## Done when (from roadmap)
> Invalid connections cannot be made

## Automated checks
- [ ] `test_port_check_fixtures.py`: the engine's `port_mismatch` issues match `schemas/fixtures/port-checks.json` for every case.
- [ ] `ports.test.ts`: the browser mirror gives the same node ids for every fixture case; `FINDINGS_PROPERTIES` matches `schemas/findings.v1.json`.
- [ ] `edits.test.ts`: `newMismatches` / `blockReason` block a Move up, a Move to…, a Remove that joins two typed steps, and a Replace with a `dedupe` reduce, each when it adds a mismatched connection; an edit that keeps or removes an existing mismatch is allowed.
- [ ] `builder.test.tsx`: blocked items are disabled with their reason (Move to… target, Remove, a palette kind); `apply` refuses a blocked edit; a mocked `validate` answer puts the issue on its card, in the count and in the issues list; the list's node button selects the node; "Could not check the workflow." with Retry; no validate call while there are no edits.
- [ ] `api` tests: one debounced call for quick edits; the previous issues stay while a check is in flight.
- [ ] `uv run pytest`, `pnpm lint && pnpm typecheck && pnpm test` green.
- [ ] `pnpm test:e2e` (axe and layout suites): no new failures against `main` (see the known stale console specs); builder screenshots updated if needed.
- [ ] CI green.

## Manual / demo checks
- [ ] Store a typed workflow (or open the audit template with `/templates` → Edit in builder and give two consecutive agents an `output_schema` / `input_schema` that do not fit through the side panel): the consumer's card shows the `port_mismatch` message within about half a second, the status line counts it, and the issues list names the node; clicking it selects the card.
- [ ] Fix the schema: the issue goes and the status line reads "Ready to run" (with no other issues).
- [ ] With a fitting typed pair A → B → C where B passes what C needs and A does not: Remove on B, Move to… "After A" for C, and Move up on C are disabled with the reason; with a merging reduce, Replace with… `dedupe` before a consumer that does not take findings is disabled.
- [ ] Do the above from the keyboard; the disabled items are announced with their reason.
- [ ] Stop the API: "Could not check the workflow." with Retry; editing and Save still work once it is back.
- [ ] Look at the builder at 375 and 1440 px, light and dark: the issues list fits (popover / bottom sheet), no horizontal page scroll.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/tech-stack.md` (Builder canvas, Typed ports, Node manifests, decisions log) and `CHANGELOG.md` updated in the PR
- [ ] No engine, API or graph-op behaviour change in the diff (only the new fixture and its test on the engine side)
