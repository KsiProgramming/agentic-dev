# Validation: Typed ports: input/output JSON Schemas validated at each edge

## Done when (from roadmap)
> A wrong-shaped output fails at the edge with a clear error

Made checkable: a run whose agent outputs JSON that breaks its `output_schema` (or prose instead of JSON) ends `failed` at that node. The `node_failed` event carries the one-line error, which names the node, the side and the JSON pointer, and a `port` payload. The console's banner names the step, and its Output tab lists the pointer and message. The same holds on the input side, where the error is on the consumer and names the producer.

## Automated checks
- [ ] `uv run pytest packages/engine`:
  - `ports.py` unit tests: schema checks (bad dialect, non-object root, remote `$ref`, size); value validation with pointers and `best_match`; the fenced or plain JSON parse; the error text format and the 500-character cap.
  - `port_issues`: both codes, gates looked through, correct `path` and `node_id`, run order.
  - Fixtures: `valid/typed-ports.json` validates, and each `invalid/port-*.json` gives exactly its expected code.
  - `test_ports_runtime.py`: every case in plan group 2, including that an untyped spec runs exactly as before (the existing compile and run tests stay unchanged and green).
- [ ] `uv run pytest packages/api`: `/validate` returns `invalid_schema` and `port_mismatch`, and `POST /runs` refuses a broken schema with `422`.
- [ ] Exported schemas are up to date: `schemas/workflow-spec.v0.json` and `web/src/api/schema.d.ts` have no diff after a re-export.
- [ ] `uv run ruff check`, `ruff format --check`, and strict pyright/mypy.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`, covering the `PortErrors`, step view and Input tab tests.
- [ ] `pnpm test:e2e`:
  - The new console test: a typed run fails at the edge with the banner and the "Wrong shape" alert, and a JSON input passes.
  - `a11y.spec.ts` with no serious axe issues on the failed console.
  - `layout.spec.ts` screenshots at 375 and 1440 px.

## Manual / demo checks
- [ ] **Validate a mismatched spec.** `POST /workflows/typed-ports/validate` with `invalid/port-mismatch-required.json` answers `200`, `valid: false`, with a `port_mismatch` issue on the consumer and a message that names the missing property.
- [ ] **Run it locally on the fake runtime** (`docker compose up`): start a run of `valid/typed-ports.json` with input `hello`. The run fails at the first typed agent with `output of '<id>' is not JSON: …`. Restart it with input `{"findings": []}`, where the echo is valid JSON: the edge passes and the run reaches the gate.
- [ ] **Console:** open the failed run at 375 and 1440 px, in light and dark.
  - The banner reads "Failed at <step>" with the reason.
  - The Output tab shows the "Wrong shape" alert, with the pointer in mono.
  - The Input tab shows both schemas in `JsonView`.
  - There is no horizontal page scroll, and no JSON in a table cell.
- [ ] **Optional, with `AGENTIC_RUNTIME=claude`:** a typed agent answers with matching JSON, and its `data` is visible in the next node's input.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] tech-stack.md has the Typed ports contract, the two codes, the console rule and the decisions log rows. The README and CHANGELOG are updated in the same PR.
- [ ] The UI rules in CLAUDE.md are respected (semantic tokens only, `JsonView` for JSON, agent output as plain text), or any break is stated in the PR and in tech-stack.
- [ ] No agent output or schema content is rendered as HTML. No remote `$ref` is ever fetched.
- [ ] The roadmap phase is marked done by CI on the PR (open-pr).
