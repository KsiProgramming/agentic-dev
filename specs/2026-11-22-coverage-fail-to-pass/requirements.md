# Coverage and fail-to-pass

Roadmap phase: 13.4
Branch: plan/13.4-coverage-fail-to-pass

## Context

13.3 shows an approver whether a writer's change builds, whether the tests pass and whether the analyzers found anything new. It does not say whether the tests check what the spec asked for. A writer can pass every check with tests that would also pass on the old code, or with no test for a criterion at all. 13.4 adds two checks to the same evidence pack: how much of the changed code the tests run (coverage of the changed lines), and, for each acceptance criterion of the spec, a test that fails on the base and passes on the change (fail-to-pass).

It builds on:
- **13.3, the evidence pack**: the `evidence` policy on a gate in a loop, the hidden `<gate>.evidence` step, `build.test` on a writer's branch (`git archive` of its ref), the send-back through 7.8's request-changes path and the rounds rule (lessons 13). The policy's shape was left open for this phase.
- **7.8, acceptance criteria**: `spec.md` has `## Acceptance criteria`, numbered `AC-001`, `AC-002`, …, each "When …, the system shall …", and the tasker cites them.
- **13.1 and 12.2**: reads through git refs and `runs.base_sha`, so the base and a writer's branch can both be read after a restore.

It unblocks 13.5 (the approved tests become protected paths), 13.6 (reviewers read a pack with criteria) and 16.1 (fix an issue: its new test must fail before the fix).

What drives the design:
- **Principle 2 (safe by construction).** The engine decides from tool results, never from an agent's claim that a test covers a criterion.
- **Principle 5 (repo content is data).** Test names, file paths and line numbers are repo output: capped, and handed to the writer under fixed headings.
- **Principle 8 (truthful numbers).** Coverage is the share of the changed executable lines the tests ran, shown with `Percent`, never the whole repo's coverage.
- **tech-stack, Build tools (13.2) and Gate review (13.3).** No repo code runs while the network is up; reasons are fixed phrases; `build.test` stays a tool for tool nodes and the evidence step only.

## Scope

### In scope

- **Python and .NET only.** Node modules get fixed reasons (`coverage is not measured for node yet`, `per-test results are not read for node yet`), so their criteria reach a person instead of sending the work back. Node is a new roadmap phase, 13.11.
- **A criterion is linked to a test by its id in the test's name.** The id may be written with or without its hyphen, in any case, as its own token: `test_ac_001_rejects_empty_title`, `AC001_RejectsEmptyTitle`, `test_title[AC-001]`. Names come from the runner's per-test results (pytest's JUnit file, .NET's TRX), so nothing is parsed from source code.
- **`build.test` grows, additively** (`schemas/tests.v1.json`):
  - `select: ["AC-001", …]` returns `cases` per module: each test whose name holds one of the ids, with `name`, `file`, `status` and `ids` (at most 200).
  - `coverage: true` measures coverage in the same test job and returns `coverage` per module: the executable lines the change added or modified in non-test files under `path` (against `runs.base_sha`), how many the tests ran, and per file the uncovered line ranges (at most 20 files). The tool works out the changed lines itself from git refs.
  - `on: "base"` (needs `node`) runs on the base tree with the change's test files laid over it, and only the tests `select` names where the runner can filter them. A linked test that fails, errors or does not build there counts as failing on the base.
  - The coverage tools are settled by the spike: coverage.py (pinned in the image, or the project's own pytest-cov) for Python, and Microsoft.CodeCoverage (`--collect "Code Coverage;Format=cobertura"`, which ships with `Microsoft.NET.Test.Sdk`) or coverlet for .NET.
  - New fixed reasons: `coverage could not be measured`, `no changed lines to cover`, `the base run did not build`, plus the Node reasons above.
- **The evidence policy grows, additively**: `checks.coverage` (`required` / `shown` / `off`), `checks.criteria` (`required` / `shown` / `off`), `coverage_min` (0 to 100, default 80) and `criteria_from` (a Markdown run artifact written before the gate, default `spec.md`). Both new checks default to `off`, so 13.3's specs and templates behave as before.
- **The coverage check**: passed at or above `coverage_min`, or with no changed executable lines; failed below it; `error` when it could not be measured. Its detail lists the uncovered changed lines per file.
- **The criteria check**: the ids are read from the `## Acceptance criteria` section of the latest version of `criteria_from`. Each criterion is one of:
  - `proven`: a linked test fails on the base and passes on the change;
  - `untested`: no test names it;
  - `failing`: a linked test fails on the change;
  - `not_proven`: every linked test also passes on the base;
  - `unchecked`: its module cannot report per-test results, or a run errored.

  The check fails on any `untested`, `failing` or `not_proven` criterion, is `error` when the only gaps are `unchecked`, and is `skipped` when the artifact lists no criteria.
- **Send-back** through 13.3's path and its rounds counter (one counter, lessons 13): the failures go back under `## Coverage` (the uncovered lines per file) and `## Criteria` (one line per criterion that is not proven, saying why).
- **Validation**: `criteria_from` must be a Markdown artifact written before the gate (`artifact_unknown`); `coverage_min` must be in range (`invalid_evidence`). The canvas side panel edits the new fields from the manifest's JSON Schema (5.4).
- **SDD templates** ("Build from a Jira issue" and "Build from a spec file", through the shared `_build`) take `checks` (default off), `check_rounds` and `coverage_min`, as "Plan, build and review" did in 13.3. With `checks` on:
  - `commit_specs` and `approve_pr` move into `review_loop`'s body after `reviewer`, and the loop ends on the reviewer's `ok` and the gate's `approve`.
  - `approve_pr` has `evidence` on `implement`: build and tests required, analyzers `no_new`, coverage and criteria required.
  - `commit_artifacts_issues` and `links_from` accept a step of a loop body that is a root step, as `on_reject: end` does (7.8). A follow-up from a PR review (7.6) still starts at `review_loop`.
  - Instructions: the spec writer writes criteria for the behaviour the change adds; the tasker gives each criterion a test task; the lead and engineers name each test with its criterion id; the writers are told their input may be failing checks under `## Criteria` and `## Coverage`.
- **Web**: `EvidenceStrip` gets a Coverage tile (`Percent` of changed lines, "N of M changed lines", the threshold) and a Criteria tile ("N of M proven"). Under the strip go the criteria (the id in mono, the state as a `StatusBadge`, the linked tests, and before → after) and the uncovered lines (`TruncatedPath` and line ranges). It keeps the three states and appears wherever the strip does today.
- **13.3's leftovers that this phase relies on**: the spike on real Node and Python repos that 13.3 did not run (to confirm its Jest, Vitest, node:test and pytest parsing) and 13.3's missing Docker fixture tests for Node and Python.
- **Specs and docs**: tech-stack (Tool layer, Sandbox if the image changes, Gate review, UI design system → Gate evidence, the SDD templates, the decisions log), the roadmap (13.4's plan link, a note on its Python and .NET scope, and the new 13.11 row), `docs/security/security-model.md` (the base run executes the change's tests offline) and `CHANGELOG.md`.

### Out of scope

- Node coverage and per-test results: **13.11** (new), "Node coverage and per-test results".
- Go, Rust and Java: no test runner yet (13.2, 13.3).
- Stopping a writer from editing the tests that judge it: 13.5. Until then a writer can weaken a linked test, and the PR says so.
- Mutation scores and "passes k times in a row": they stay in `ideas.md`.
- Coverage of the whole repo, or trends across runs.
- Criteria linked by markers, tags or an agent-written map (considered and not chosen).
- Turning `checks` on by default in the SDD templates (see Open questions).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Ecosystems | Python and .NET; Node gets fixed reasons and a new phase, 13.11 | Chosen in the interview. Node's per-test results and coverage depend on the repo's test script and reporters (13.3's findings), and its coverage needs a package the repo may not have. |
| How a criterion is linked to tests | The criterion id in the test's name, read from the runner's per-test results | Chosen in the interview. It is deterministic, readable in the repo and the same for every runner. An agent-written map would be a claim to verify, and markers or tags need a reader per runner. |
| What "fails before" means | The change's test files laid over the base tree; a linked test that fails, errors or does not build there fails before | This is SWE-bench's fail-to-pass. A new test usually cannot even import the base's code, and that is still a test the change makes pass. |
| Where coverage of changed lines is worked out | In `build.test`, from git refs against `runs.base_sha` | The raw coverage data stays in the sandbox, and only a bounded summary leaves it. The base is the one 12.2 already records. |
| Defaults of the new checks | `off` | 13.3's specs, templates and AC-2's conformance check stay unchanged. |
| A criterion that cannot be checked | `unchecked`, so the check is `error` and the gate pauses for a person | 13.3's rule: a failure that is not the writer's never sends the work back. |
| Send-back | 13.3's path and rounds counter, new headings `## Coverage` and `## Criteria` | One counter for all checks (lessons 13); no second mechanism. |
| SDD templates | Adopt evidence by option `checks`, which moves `commit_specs` and `approve_pr` into `review_loop` | 13.3 left SDD unchanged because `commit_specs` had to be a root step. Allowing it in a loop body that is a root step mirrors 7.8's `on_reject: end` rule and keeps one gate for the person. |
| Order of work | Spike first, then the tool, the policy, the templates and the web, in one PR | Chosen in the interview. The spike settles the coverage tools offline before the contract is fixed (lessons 10 and 14). |
| Real run | Read step by step in the console, with **GitHub Copilot** as the provider | Chosen in the interview. This is a one-off deviation from lessons rule 1's wording, recorded in the PR as 13.3 did. Rule 1 stays as it is. |

## Open questions

- **Python coverage source.** coverage.py pinned in the sandbox image and put on the job's path, or the project's own pytest-cov when it has one. The spike decides. The default is coverage.py from the image, so every pytest project is measured.
- **.NET coverage source.** Microsoft.CodeCoverage's cobertura output (no package added) or coverlet when the test project references it. The spike decides. The default is Microsoft.CodeCoverage.
- **A criterion the base already meets** (behaviour the change must keep) can never be proven, so it is sent back until the rounds run out and a person decides. The default keeps that, and tells the spec writer to write criteria only for what the change adds. The alternative is a state of its own that does not send back.
- **A test project the base cannot build** makes every linked test in it fail before. A writer could use that to prove a criterion with a weak test. The default accepts it and shows "did not build on the base" at the gate; 13.5 and 13.6 narrow it.
- **Where 13.11 is listed.** The default is the end of Milestone 13's table, worked after 13.10.
- **SDD `checks` by default.** Off in this phase, as 13.3 did for "Plan, build and review". Turning it on is a later decision, made after real runs.
