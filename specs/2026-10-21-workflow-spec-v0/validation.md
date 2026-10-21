# Validation: Workflow spec v0

## Done when (from roadmap)
> A sample spec validates and an invalid one is rejected in tests

## Automated checks
- [ ] `test_spec.py::test_valid_spec[*]`: each of the three valid fixtures parses, and its JSON round-trip gives an equal model.
- [ ] `test_spec.py::test_invalid_spec[*]`: each of the eight invalid fixtures raises `ValidationError`, at the expected `loc` or with the expected message substring:
  - unknown type
  - missing field
  - extra key
  - duplicate id (the message names the id)
  - empty sequence
  - bad id
  - wrong `spec_version`
  - unknown provider
- [ ] Schema smoke test: `schemas/workflow-spec.v0.json` has a `oneOf` with a discriminator on `type` that covers `agent` and `sequence`.
- [ ] CI schema freshness step: it re-exports the schema and `git diff --exit-code -- schemas/` passes. To check it really guards the schema, change a model field without re-exporting; the step must fail.
- [ ] Existing CI jobs are green: `ruff check`, `ruff format --check`, `pyright` (strict), `pytest`, and the web and API-contract jobs, which this phase leaves unchanged.

## Manual / demo checks
- [ ] Run `uv run pytest packages/engine/tests/test_spec.py -v`. Expected: every valid and invalid case is listed and passes.
- [ ] Run `uv run python scripts/export_workflow_schema.py`, then `git diff --exit-code schemas/`. Expected: no diff, because the committed schema is current.
- [ ] Read one rejection error, for example for `duplicate-node-id.json`. Expected: it points at the offending node, so a user could act on it.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] The scope matches `requirements.md`: only `agent` and `sequence`, and no policy, ports or CEL.
- [ ] The schema and fixtures are committed, and the README links them.
- [ ] Roadmap phase 0.2 is marked done in the PR (`complete-phase` skill or the CI check).
