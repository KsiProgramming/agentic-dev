# Plan: Coverage and fail-to-pass

One PR, in this order. Each group leaves the tree working: the new checks default to `off` until group 4 turns them on in the SDD templates.

## 1. Spike on real repos (`findings.md`)

Run each step in the current sandbox image, with the registry proxies up, restore on the registry network and tests on `none` (lessons 10 and 14).

- [ ] Python sample repos: pytest with `uv.lock` (pytest in a dependency group) and with `requirements.txt`. Check:
  - coverage.py from a pinned wheel in the image vs the project's pytest-cov;
  - `coverage json` with `--source` set to the module, so files that were never imported count as uncovered;
  - JUnit (`xunit2`) gives every test's name and status, and a file for each test (from `classname` if there is no `file` attribute).
- [ ] .NET sample repos: xUnit with only `Microsoft.NET.Test.Sdk`, and one that also references `coverlet.collector`. Check:
  - `dotnet test --collect "Code Coverage;Format=cobertura"` offline, against coverlet's `XPlat Code Coverage`;
  - the TRX gives every test's name and outcome;
  - how `--filter` selects tests by an id in their name.
- [ ] Fail-to-pass on both: lay a change's test files over the base tree and run only the linked tests. Write down:
  - what a new test that imports a new symbol gives (a pytest collection error, a C# build error);
  - which files must be laid over (the test file, `conftest.py`, the test project's other changed files).
- [ ] Id matching: one regex for `AC-001`, `ac_001`, `AC001` as a token, tried on real pytest, parametrized pytest and xUnit names. It must not match `TRACK001` or `AC-0011`.
- [ ] 13.3's leftover: run `build.test` on a Jest, a Vitest and a `node:test` repo, and on the `uv.lock` pytest repo, to confirm 13.3's count parsing on real output. Fix what fails, with a lessons entry if a real run shows a gap.
- [ ] `specs/2026-11-22-coverage-fail-to-pass/findings.md`: each choice, what it rests on, verified or not. Add the decisions-log rows.

## 2. `build.test`: cases, coverage and a base run (`packages/tools`, `packages/sandbox`)

- [ ] `agentic_tools.build.tests`:
  - `TestCase` (`name`, `file`, `status`, `ids`) and `ChangedCoverage` (`changed`, `covered`, `files: [{path, changed, covered, uncovered: [[start, end], …]}]`, `truncated`) on `TestCheck`;
  - `parse_junit` and `parse_trx` keep every test's result, not only failures;
  - `criterion_ids(name)`, the regex from the spike.
- [ ] `agentic_tools.build.server` and `runner`: the `select`, `coverage` and `on` arguments, through `strict_tool`. With `on: "base"`:
  - it needs `node`;
  - the work copy is `archived_tree` of the checkout (the base) with the change's test files laid over it from the writer's ref (an overlay option in `agentic_tools.tree`);
  - a run that does not build gives `the base run did not build` and fails every linked test there.
- [ ] Changed lines: `git diff -U0 <base>..<ref>` through `agentic_sandbox.refs`, for non-test files under `path`, intersected with the coverage report's executable lines.
- [ ] Python coverage: `python -m coverage run --source=<module> -m pytest …`, then `coverage json`, both in the offline test job. .NET: the collector the spike chose, with the cobertura file read from the job's output after a marker, as the TRX is.
- [ ] Node: `coverage` and `select` give the fixed reasons `coverage is not measured for node yet` and `per-test results are not read for node yet`.
- [ ] If the spike picks coverage.py from the image: a pinned wheel checked against its sha256 in `packages/sandbox/Dockerfile`, with its size noted.
- [ ] Regenerate `schemas/tests.v1.json`.
- [ ] Unit tests in `test_build_test.py` and `test_build_dotnet_test.py`: parsing every case, id matching, changed-line maths (added, modified, deleted, a renamed file, a file with no executable change), caps.
- [ ] Docker tests in `test_build_docker.py` (real job containers, see validation).

## 3. Evidence policy and pack (`packages/engine`)

- [ ] `agentic_engine.spec.models`: `EvidenceChecks.coverage` and `.criteria` (`required` / `shown` / `off`, default `off`), and `GateEvidence.coverage_min` (0 to 100, default 80) and `.criteria_from` (default `spec.md`). Validation: `artifact_unknown` for a `criteria_from` no node writes before the gate, `invalid_evidence` for a non-Markdown name. The manifest's JSON Schema is regenerated so the side panel shows the fields.
- [ ] `agentic_engine.evidence`:
  - `CheckKind` gains `coverage` and `criteria`, and `TITLES` gains "Coverage" and "Criteria";
  - `criteria_ids(markdown)` reads the `## Acceptance criteria` section;
  - `coverage_check` and `criteria_check` build the checks from the change run and the base run (states `proven`, `untested`, `failing`, `not_proven`, `unchecked`);
  - `send_back_comments` writes `## Coverage` (uncovered ranges per file) and `## Criteria` (one line per criterion that is not proven, with why). Everything is capped and stays data.
- [ ] `collect`:
  - the change's `build.test` call gains `coverage` and `select` when those checks are on;
  - a second call with `on: "base"` runs only when criteria are on and some test is linked;
  - the criteria artifact is read through the run's artifacts at the step;
  - the base run is per pass (the tests change), never cached.
- [ ] `schemas/evidence.v1.json` regenerated (additive).
- [ ] Tests in `test_evidence_gate.py`:
  - each criterion state;
  - coverage above, below and at the threshold, and with no changed lines;
  - `unchecked` reaches a person;
  - the writer's next input holds `## Criteria` and `## Coverage`;
  - a restart between the evidence step and the gate runs no job twice;
  - one rounds counter across all checks;
  - 13.3's existing tests are unchanged with the new checks off.

## 4. SDD templates (`packages/engine/templates/sdd.py`)

- [ ] `SddFileParams`: `checks` (default off), `check_rounds` (below `max_passes`, which must be at least 2 with `checks`) and `coverage_min`, checked as in `PlanBuildReviewParams`.
- [ ] In `_build`, with `checks`: `commit_specs` and `approve_pr` go into `review_loop`'s body after `reviewer`, and `approve_pr` gets `evidence`:
  - `node: implement`;
  - build and tests `required`, analyzers `no_new`, coverage and criteria `required`;
  - `criteria_from: spec.md`, `max_rounds: check_rounds`.

  `until` becomes the reviewer's `ok` and the gate's `approve`.
- [ ] `commit_artifacts_issues` and the `links_from` check accept a step of a loop body that is a root step. Validation tests for both.
- [ ] Instructions:
  - spec writer: criteria describe what the change adds;
  - tasker: one test task per criterion, named with its id;
  - lead and engineer: name each test with its criterion id, and the input may be failing checks under `## Criteria` and `## Coverage`;
  - reviewer: reads the evidence.

  Tests assert what each agent receives (lessons 1).
- [ ] Template tests for both builders with `checks` on and off. The worker's AC-5 and spec-file tests run once more with `checks` on, on the fake GitHub, and the 7.6 follow-up test still starts at `review_loop`.

## 5. API and web (`packages/api`, `web/`)

- [ ] `GET /runs/{id}/gate` and `gate_waiting` carry the larger pack unchanged in shape. Add an API test with a coverage and a criteria check (run from `packages/api`).
- [ ] Regenerate the web API client.
- [ ] `web/src/runs/console/evidence-strip.tsx`:
  - a Coverage tile (`Percent`, "N of M changed lines", the threshold) and a Criteria tile ("N of M proven"), with the status through `StatusBadge` and its labels from one map;
  - under the strip, the criteria list (the id in mono, the state, the linked test names in mono, and before → after) and the uncovered lines (`TruncatedPath` and ranges), at most eight each, then "and N more".

  Read `specs/design-language.md` and `web/AGENTS.md` first.
- [ ] `evidence-strip.test.tsx`: each criterion state, coverage pass and fail, the Node reasons, loading, empty and error.
- [ ] e2e: the gate review with a pack that holds coverage and criteria, in `layout.spec.ts` and `a11y.spec.ts` (helpers in `runs.ts`).

## 6. Specs, docs and the real run

- [ ] tech-stack:
  - Tool layer → Build tools: `build.test`'s `select`, `coverage` and `on`;
  - Sandbox: the image, if it changed;
  - Gate review → Evidence: the policy fields, the two checks and the states;
  - UI design system → Gate evidence: the tiles and the lists;
  - Build from a Jira issue template: `checks`, and remove "the acceptance criteria checked against tests (13.4)" from "Not yet";
  - decisions-log rows.
- [ ] roadmap:
  - 13.4's plan link and a line saying it covers Python and .NET;
  - a new row **13.11 Node coverage and per-test results** (Jest, Vitest and node:test give each test's result and the coverage of changed lines offline, so 13.4's checks work on Node modules; done when an SDD run on a Node repo's gate shows its coverage and its criteria proven by fail-to-pass), listed at the end of Milestone 13.
- [ ] `docs/security/security-model.md`: the base run executes the change's test files on the base, offline, in a job container outside the checkout.
- [ ] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] The real run on Copilot (see validation). Anything it finds goes into `specs/lessons.md` in this PR.
