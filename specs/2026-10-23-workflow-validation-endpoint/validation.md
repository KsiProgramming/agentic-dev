# Validation: Validation endpoint `POST /workflows/{id}/validate`

## Done when (from roadmap)
> Invalid specs return actionable errors

"Actionable" means every issue has a stable `code`, the `path` and (where one exists) the `node_id` to fix, and a `message` that says what to change. Every problem in a spec is reported in one response, not only the first.

## Automated checks
### Engine unit tests (`packages/engine/tests/test_validate.py`, no database)
- [ ] The sample spec, every template's built spec (`TEMPLATES`) and the fixtures in `tests/fixtures` validate with no issues.
- [ ] One invalid fixture per code. Each test asserts the `code`, the `path`, the `node_id` and that the `message` names the node and the fix:
  - `schema`: a missing `role`, an unknown node `type`, an extra field, a bad node id pattern. The path is the spec path (`root.steps[1].role`), with no Pydantic union tags;
  - `duplicate_node_id`;
  - `invalid_expression` for a loop `until` and a map `over`;
  - `not_allowed_in_loop` (a gate in a loop body) and `not_allowed_in_map` (a writer in a map body);
  - `reference`: `reduce.from` naming a later node, a non-map or itself; a publisher's `from_node` naming a non-writer or a later node;
  - `publish_without_gate`;
  - `unknown_tool` on an agent and on a tool node;
  - `policy_limit` for loop iterations, map concurrency and nesting depth against a lowered policy, with `limit` and `value` set;
  - `budget_unpriced_model` when a budget is set, and no such issue when it is not.
- [ ] A spec with three different problems returns three issues in run order.
- [ ] A spec that fails the schema returns only `schema` issues and does not raise.
- [ ] The existing `test_spec.py`, `test_policy.py` and `test_budget.py` still pass: the model validators still refuse the same specs.

### API integration tests (`packages/api/tests/test_workflows.py`, Testcontainers Postgres)
- [ ] A valid spec gives `200 {valid: true, issues: [], policy}`, and `policy` equals the workspace's effective policy.
- [ ] An invalid spec gives `200 {valid: false, issues: […]}` with the expected codes and paths.
- [ ] A path `{id}` that differs from `workflow.id` gives an `id_mismatch` issue next to the other issues.
- [ ] A workspace with lowered limits (`PUT /workspaces/{id}/policy`) makes a spec that is valid on the platform policy report `policy_limit` issues.
- [ ] `budget_usd` in the body with an unpriced model gives `budget_unpriced_model`. Without a budget there is no such issue.
- [ ] An unknown `workspace_id` gives `404`, and a `workflow` that is not an object gives `422`.
- [ ] The endpoint writes nothing: the run, event and approval counts are unchanged after a call.
- [ ] `POST /runs` above the workspace limits returns `422` with both `errors` (strings, unchanged) and `issues` (same items as validate). `POST /runs` with an unknown tool name returns `422` and creates no run.
- [ ] The existing `test_runs.py` and `test_policy.py` pass unchanged.

### CI
- [ ] `ruff check`, `ruff format --check`, strict type check (`pyright`/`mypy`) and `pytest` are green for every package.
- [ ] The web lint, typecheck and tests are green with the regenerated `schema.d.ts`.

## Manual / demo checks
- [ ] With `docker compose up`, post a spec with a gate inside a loop and a map with `max_concurrency: 20`:
  ```bash
  curl -s -X POST localhost:8000/workflows/demo/validate -H 'content-type: application/json' -d '{
    "workflow": {"spec_version":"0","id":"demo","name":"Demo","root":{"type":"sequence","id":"main","steps":[
      {"type":"loop","id":"review","until":"true","max_iterations":3,
       "body":{"type":"gate","id":"ok","title":"OK?"}},
      {"type":"map","id":"each","over":"[\"a\"]","max_concurrency":20,
       "body":{"type":"agent","id":"w","role":"r","instructions":"i","tools":["repo.nope"]}}]}}}' | jq
  ```
  Expected: `valid: false` with one `schema` issue at `root.steps[1].max_concurrency` (node `each`, above the ceiling of 8). Only schema issues are returned while the schema fails. Set `max_concurrency` to 4 and send it again. Expected: `not_allowed_in_loop` (node `ok`, path `root.steps[0].body`: the node to move out of the loop) and `unknown_tool` (node `w`, path `root.steps[1].body`), in that order.
- [ ] The same spec with every problem fixed returns `valid: true`.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] Roadmap row 3.4 marked done (`complete-phase`), and a CHANGELOG entry under `[Unreleased]`.
- [ ] `specs/tech-stack.md` documents the endpoint, the issue codes and the decision row.
- [ ] No secrets or keys appear in responses or logs (the endpoint reads prices and limits only).
