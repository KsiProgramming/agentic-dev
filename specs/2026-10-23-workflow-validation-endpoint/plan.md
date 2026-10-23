# Plan: Validation endpoint `POST /workflows/{id}/validate`

Engine first, then API, then the shared `422` shape. The project stays green after each group.

## 1. Issue model and structured checks (engine)
- [ ] Add `ValidationIssue` (`code`, `path`, `node_id`, `message`, optional `limit`, `value`) and the `IssueCode` literal to `agentic_engine/spec/models.py`. Export them from `agentic_engine.spec`.
- [ ] Change `loop_errors`, `map_errors`, `publish_gate_errors`, `policy_errors` and `budget_errors` to return `list[ValidationIssue]`. Each issue carries the path and node id it already builds into its string. Give each message a "what to change" clause where it lacks one (for example "lower max_iterations to 5 or less").
- [ ] Split the publish check's reference cases (missing or later `from_node`, `from_node` naming itself, not a writer) into `reference` issues and keep `publish_without_gate` for the missing gate. Do the same for `reduce.from` (`reference`).
- [ ] Keep the `WorkflowSpec` model validators raising `ValueError` built from the issues' messages, so building a bad spec is still impossible and existing tests keep passing.
- [ ] Update the callers in `agentic_store` (`PolicyViolationError`) and the engine (`budget.py`, if it uses the strings) to carry issues.
- [ ] Resolve the open question: find where the worker registers tools, and expose the platform's tool names (e.g. `agentic_tools.PLATFORM_TOOL_NAMES`) from that same code.

## 2. `validate_workflow` (engine)
- [ ] Add `agentic_engine/spec/validate.py` with `validate_workflow(raw, *, policy, priced, default_model, known_tools) -> list[ValidationIssue]`.
- [ ] Schema pass: `WorkflowSpec.model_validate(raw)`. On `ValidationError`, map each error to a `schema` issue: turn `loc` into the spec path (`root.steps[0].role`, drop the discriminator tags Pydantic adds), find the nearest node id from `raw`, and keep Pydantic's message. Errors raised by our model validators are not reported here: run the structural checks on a spec built with `model_construct`, or have the validators read from a shared function. Pick whichever keeps the validators as the single guard.
- [ ] Structural pass on the parsed spec: duplicate ids, loop rules, map and reduce rules, references, gates, unknown tools (`node_tools` against `known_tools`) and CEL expressions.
- [ ] Policy pass: `policy_errors(root, policy)` and `budget_errors(...)` when `policy.budget_usd` is set.
- [ ] Order the issues depth first in run order. Never raise for a bad spec.

## 3. Endpoint (API)
- [ ] New `packages/api/src/agentic_api/workflows/` with `models.py` (`ValidateWorkflowRequest`, `ValidateWorkflowResponse`) and `routes.py` (`POST /workflows/{workflow_id}/validate`, `operation_id="validateWorkflow"`, tag `workflows`). Register it in `app.py`.
- [ ] Resolve the workspace (default if omitted, else `404`). Build the policy as `POST /runs` does (`effective_policy` and `with_budget`), with the priced lookup from the workspace's price table and the default model.
- [ ] Add an `id_mismatch` issue when `workflow_id != raw["id"]`, and still report every other issue.
- [ ] Return `200 {valid, issues, policy}`. Document the codes and the `200`-on-invalid rule in the route docstring (it becomes the OpenAPI description).

## 4. Same shape on `POST /runs` and rerun
- [ ] Add `issues: list[ValidationIssue]` to `PolicyErrorDetail`, filled from `PolicyViolationError`. Keep `errors: list[str]`.
- [ ] Before creating the run, `POST /runs` with `workflow` rejects unknown tool names with `422`, through the same validator, so the run is not started.

## 5. Contract and docs
- [ ] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts` (`npm run gen:api`). The web typecheck stays green.
- [ ] Add the validation endpoint to `specs/tech-stack.md` (a short "Workflow validation (API contract)" section with the issue codes), and a decisions-log row: "Validation answers 200 with structured issues".
