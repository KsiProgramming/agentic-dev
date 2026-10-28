# Plan: Typed ports: input/output JSON Schemas validated at each edge

## 1. Spec fields and schema checks
- [ ] Add `jsonschema` to `packages/engine/pyproject.toml` and run `uv lock`.
- [ ] New `agentic_engine/ports.py`:
  - `check_schema(schema) -> str | None`: valid 2020-12 (`Draft202012Validator.check_schema`), root `"type": "object"`, only local `$ref`s, at most 16 KB.
  - `validate_value(schema, value) -> list[PortError]`: `{pointer, message}`, `best_match` first, at most 10.
  - `parse_output(text) -> dict | ParseError`: the whole text as JSON, or the single fenced block it holds.
  - `port_error_text(side, node_id, from_node_id, errors)`: the one-line message, at most 500 characters.
- [ ] `spec/models.py`:
  - `input_schema` and `output_schema` (`dict[str, JsonValue] | None`, with descriptions) on `AgentNode` and `ToolNode`.
  - `invalid_schema` and `port_mismatch` in `IssueCode`.
- [ ] `port_issues(root)` in `spec/models.py`:
  - `invalid_schema` for each broken schema.
  - `port_mismatch` for consecutive steps of each sequence. Gates are looked through. The rule is a required property that is not declared, or a different top-level `type`.
  - Wired into `structure_issues`, so `POST /runs` refuses the spec too.
- [ ] Fixtures in `packages/engine/tests/fixtures/specs/`:
  - Valid: `typed-ports.json`.
  - Invalid: `port-invalid-schema`, `port-not-object`, `port-remote-ref`, `port-mismatch-required`, `port-mismatch-type`.
- [ ] Unit tests for `ports.py` and `port_issues`.
- [ ] Re-export `schemas/workflow-spec.v0.json`.

## 2. Runtime edge checks in the engine
- [ ] `agent.py`: `OUTPUT_SCHEMA_INSTRUCTION`, added in `to_request` when `output_schema` is set (the schema as compact JSON after it).
- [ ] `graph/compile.py` `_run_step`:
  - Before `run()`: check the input against `input_schema`. A failure logs `node_started` and then `node_failed` with `port`, and returns a failed result. No agent starts and no agents-alive slot is taken. The node still counts once toward agents spawned, as any agent node that was reached does.
  - After a completed agent or tool result: check the output against `output_schema`.
    - On success, return the result with `data` set to the parsed object and `text` set to canonical JSON.
    - On failure, return it `failed`, with `error` and `port`, and its usage kept.
  - Pass `port` into the `node_failed` payload.
  - Map items and parallel branches go through the same function, so they need no separate code. Check that `from_node_id` is the previous step in a sequence, and `None` for a first step, a map item or a branch.
- [ ] Tests on the fake runtime in `packages/engine/tests/test_ports_runtime.py`:
  - Typed output OK: `data` is set and the next node gets the JSON.
  - A fenced answer is parsed.
  - Prose fails with "is not JSON".
  - A wrong shape fails with its pointer.
  - An input mismatch fails the consumer, and its agent never starts.
  - A tool's `data` is checked.
  - A typed node inside a map item and inside a parallel branch (join `any` survives one bad branch).
  - CEL reads `results.x.data`.
  - An untyped spec is unchanged (the existing tests stay green).

## 3. API contract and validation endpoint
- [ ] `packages/api` tests:
  - `/validate` returns `invalid_schema` and `port_mismatch` with path and node.
  - `POST /runs` refuses a broken schema with `422`.
- [ ] Re-export the OpenAPI spec and `web/src/api/schema.d.ts`. Add the `port` payload type to `web/src/runs/types.ts`.

## 4. Run console
- [ ] `web/src/runs/console`:
  - A `PortErrors` component (alert, "Wrong shape", the side and the source node, the pointer in mono with the message as text, "Show all" after 5).
  - Shown at the top of the Output tab of a step whose `node_failed` has `port`.
  - Use `@/components/ui/alert` and the status tokens, with no raw colours.
- [ ] Input tab: "Input schema" and "Output schema" sections in `JsonView` for a typed agent or tool node.
- [ ] The timeline and step entries carry `port` from the `node_failed` payload.
- [ ] Vitest:
  - `PortErrors` renders pointers and messages, and its "Show all" works.
  - The step view shows the alert for a port failure.
  - The Input tab shows the schemas.
- [ ] Playwright (`web/e2e/console.spec.ts`, with a `TYPED` helper in `e2e/runs.ts`):
  - Start a run whose typed writer echoes "hello" on the fake runtime.
  - The console banner reads "Failed at writer" with the "is not JSON" reason.
  - The Output tab shows the "Wrong shape" alert.
  - A second run with a JSON input passes the edge.
  - Add the failed console to `a11y.spec.ts` and to the `layout.spec.ts` screenshots at 375 and 1440 px.

## 5. Docs and specs
- [ ] `specs/tech-stack.md`:
  - A "Typed ports (API contract)" section (fields, dialect, rules, edge checks, the error text and the `port` payload).
  - `invalid_schema` and `port_mismatch` in the validation codes.
  - The "Wrong shape" alert under Run console → Selected step.
  - Decisions log rows for the library and the JSON production.
- [ ] README "Typed ports" section, with the example spec.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] Roadmap: leave the status to CI (open-pr). The "Next up" line change goes in its own small PR (see requirements, Open questions).
