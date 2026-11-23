# Protect the grader

Roadmap phase: 13.5
Branch: plan/13.5-protect-the-grader

## Context

13.3 and 13.4 made the platform judge a writer's work before a person sees it: the build, the tests, the analyzers, the coverage of the changed lines and a fail-to-pass test for each acceptance criterion. Every one of those checks reads files the writer can change. A writer told to make the tests pass can weaken an assertion, change a CI workflow or relax an analyzer rule, and the checks will pass. 13.3's and 13.4's PRs both say so. 13.5 makes the platform protect what judges a writer.

Today `repo.write_file` is the only way an agent changes a file, and `repo.commit` commits what it wrote. Tool rights are granted per node, but not per path. Every writer's branch starts at the run's base (`runs.base_sha`). 13.1 left "starting a writer's branch on top of an earlier writer's branch" to this phase, so in a test-first flow the implementer cannot yet start from the approved tests.

It builds on:
- **1.6 and 6.3/6.9**: writer branches, integration branches and `start_branches`, which already starts task branches from another branch.
- **12.2 and 12.4**: saved bundles and rerun from a step. Both must keep a writer's start point and its frozen files.
- **13.1**: `ReadableWriters` (the engine hands per-step state to the repo tools), "# Work before you" and `node_started.writers`.
- **13.3 and 13.4**: the evidence step, `scan.lint {node}` on an archived tree, `is_test_path`, the criteria check and the SDD `checks` option.

It unblocks 13.10 (only the verification node may mark a feature as passing), 19.7 (an approved contract is a protected path), 10.6 (protected paths checked on an external agent's diff) and 20.6 (protected-path attempts as a quality metric).

What drives the design:
- **Principle 2 (safe by construction).** The engine enforces protection in the tools, not in instructions. Platform defaults apply even when a workflow names nothing.
- **Principle 3 (humans approve).** A change to a protected path needs its own node and a gate after it.
- **Principle 4 (tools live in the platform).** The refusal is in the `repo` server, so it behaves the same on Claude and Copilot, and for orchestrator tasks.
- **Principle 6 (transparency).** Every refused attempt is an event, counted on the run and shown at the gate.
- **Lessons 1 and 5.** This phase changes what writers receive and adds a new place a writer's branch can start. So it writes down what every agent of the test-first flow receives and reads, with tests.

## Scope

### In scope

- **Protected paths in the workflow spec**: `protect: {paths: [glob, …], allow: {<node>: [glob, …]}}` on `WorkflowSpec`.
  - `paths` are protected for every writer.
  - `allow` lets a named writer change protected paths that match its globs. Validation requires a gate after such a node, before any later writer starts from it and before any publish.
- **Platform defaults, always on.** They apply even with no `protect`, at any depth, and only `allow` exempts a node:
  - CI: `.github/workflows/**` and `.github/actions/**`;
  - analyzer and scanner config: `.editorconfig`, `.globalconfig`, `*.globalconfig`, `*.ruleset`, `Directory.Build.props`, `Directory.Build.targets`, `ruff.toml`, `.ruff.toml`, `biome.json`, `biome.jsonc`, `.shellcheckrc`, `.gitleaks.toml` and `.gitleaksignore`.

  The list lives in one place in the engine, is written into tech-stack and is shown wherever the rules are.
- **The evidence thresholds** are already out of the writer's reach: they live in the gate's `evidence` in the spec, and the evidence step ignores repo-side thresholds such as coverage's `fail_under`. Tech-stack says so; nothing in the repo needs protecting for them.
- **Refusal in the repo tools.**
  - `repo.write_file` refuses a protected path before it writes anything.
  - `repo.commit` refuses a commit whose staged paths include one. This catches a write through a symlinked directory, and both sides of a rename.
  - Both use fixed texts that say why: the platform's default, the workflow's pattern, or "approved at `<gate>` from `<writer>`".
  - This covers every writer, orchestrator tasks included. The engine hands the rules to the tools per step through a `ProtectedPaths` object (`agentic_runtime.tools`), the pattern of `ReadableWriters`.
- **Test-first: `start_from`.** A writer agent, or an orchestrator whose body writes, may set `start_from: <writer>`.
  - Its branch starts at that writer's tip. For an orchestrator, its integration branch does, and so every task's branch.
  - The branch is made before its first turn, so a hub plans from the approved work.
  - Every file the earlier writer changed against the base is frozen for it and its tasks: they can read those files but not write them.
  - Validation: `start_from` must name a writer that completes before the node, with a gate between them, and the node cannot be in a map or a parallel.
  - The start point and the frozen files are kept in the checkpointed state. A resume, a restore from saved bundles (12.2) and a rerun from a step (12.4) give the same answer.
- **Matching**:
  - on the repo-relative normalised path;
  - globs with `**` (any depth), `*` and `?`;
  - case-insensitive, because a checkout on Windows or macOS treats case variants as one file and refusing more is the safe side.

  One matcher, used by the tools and the validator.
- **Attempts are events.** Each refusal writes `protected_path_refused` with `node_id`, `tool`, `path` and `rule` (`default`, `workflow` or `frozen`, plus the pattern or the writer it came from). A refusal is not a send-back and does not pause the run.
  - `GET /runs` and `GET /runs/{id}` return `protected_attempts`, the count.
  - `gate_waiting` and `GET /runs/{id}/gate` carry `protected_attempts`: per writer the gate shows, grouped by path, capped.
- **Agents told up front.** Every writer gets a "# Protected paths" section after "# Work before you": the default list, the workflow's patterns, and the frozen files with the gate that approved them. It says the writer can read them but not write them, that a refusal is counted, and that if one must change it should say so in its answer.
  - The engine writes the section from the spec and the run's state, never from model output.
  - `node_started` carries `protected`, so the console's Input tab shows it.
- **The gate's changes mark protected files.** A `changes` entry that matches a protected path carries `protected` and its rule (for example, a change made by an allowed node). A writer that a later writer started from is shown inside that writer's diff, not listed a second time.
- **Analyzers use the base's config.** In the evidence step, the change-side `scan.lint {node}` runs with `config: "base"`:
  - the base's analyzer config files (the default list) are laid over the writer's archived tree, added, replaced or removed to match the base;
  - ruff reads the base's `[tool.ruff]` when a module's `pyproject.toml` changed it.

  This is always on in the evidence step. `scan.lint` without `config` behaves as before. A short spike settles the mechanism on a real ruff repo and a real .NET repo first (lessons 14).
- **SDD test-first option.** Both SDD builders get `test_first` (default off; it needs `checks`).
  - After `tasker`, a `tests_loop` holds `test_writer` and `approve_tests`. `test_writer` writes at least one test per acceptance criterion, named with its id, in test files only, expected to fail now. `approve_tests` is a gate with `on_changes`, writing the comments as an artifact the test writer reads.
  - `implement` gets `start_from: test_writer`.
  - The instructions for the tasker, the lead and the engineers say the approved tests are on their branch, frozen, and must be made to pass unchanged.
  - The PR carries the tests, because the integration branch starts from them.
- **Web**:
  - the gate review (approval dock sheet, Inbox and review sheet) lists the protected-path attempts and marks protected files in the file list;
  - the console header shows a tile for attempts when there are any;
  - the Input tab lists a step's protected paths;
  - the refused call has its own one-liner in Activity;
  - every data view keeps its three states.
- **A fixture workflow** for "Done when", `test-first.json`: `test_writer` → `approve_tests` → a loop with `implementer` (`start_from: test_writer`) and a gate with evidence → `publish`.
- **Specs and docs**:
  - tech-stack: Tool layer, Agent runtime "What an agent is told", Gate review, Workflow validation, UI design system → Gate evidence, the SDD template and decisions-log rows;
  - design-language, if the "Protected" mark needs a neutral badge;
  - roadmap: 13.5's plan link, and a note that SDD gets `test_first`;
  - `docs/security/security-model.md`;
  - `CHANGELOG.md`.

### Out of scope

- Sealed tests kept outside the sandbox: **17.3**.
- Protected paths as workspace policy (governance): **20.3**.
- Pausing a run that keeps trying protected paths, and node-level declared write paths: **13.7** (circuit breakers).
- Checking a vendor agent's diff for protected paths: **10.6**.
- Counts per workflow over time: **20.6**.
- Test-first in "Plan, build and review", and turning SDD's `test_first` on by default: later, after real runs.
- Resetting analyzer settings inside a `.csproj` (`NoWarn`, `AnalysisLevel`, `TreatWarningsAsErrors`), and suppressions written in code (`# noqa`, `#pragma warning disable`, `biome-ignore`): see Open questions.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where protected paths are declared | `protect` on the workflow spec, plus platform defaults in the engine | The roadmap says the workflow declares them. The spec is versioned, so a change to the rules has a diff and an audit trail (principle 1). Workspace policy is 20.3 |
| Platform defaults | Always on, with no off switch; only `allow` exempts a node, and it needs a gate after it | Chosen in the interview. Safe by construction (principle 2): a workflow that forgets `protect` still protects CI and analyzer config. An exemption is visible in the spec and gated (principle 3) |
| Where it is enforced | `repo.write_file` before writing, and `repo.commit` on the staged paths, through a `ProtectedPaths` object the engine sets per step | Tools live in the platform (principle 4), so it is the same on both providers and for orchestrator tasks. The commit check catches symlinked directories and renames that a path check alone misses |
| How a test-first implementer gets the tests | `start_from: <writer>`. Its branch, or for an orchestrator its integration branch, starts at that writer's tip | 13.1 left it here. It reuses 6.9's `start_branches`, and the PR from the implementer carries the tests |
| What is frozen | Every file the earlier writer changed against the base, not only test files | The approved work is what was approved, and 19.7's contracts work the same way. The test writer is told to change test files only, and the gate shows any other file it changed |
| What a refusal does | A fixed-text tool error, a `protected_path_refused` event, counted per run and listed at the gate; no send-back, no pause | The roadmap's "Done when". Stopping a run on its behaviour is 13.7 |
| Agents told up front | A "# Protected paths" section and `node_started.protected` | Chosen in the interview. A writer that knows the rules wastes fewer turns, and lessons 1 asks that what agents receive be visible |
| Case | Case-insensitive matching | .NET repos are often edited on Windows. Refusing a case variant is the safe side |
| Analyzer config at the evidence step | The base's config laid over the writer's tree (`scan.lint config: "base"`), always on in the evidence step | Chosen in the interview. A table inside `pyproject.toml` cannot be protected as a whole file, so the evidence must not read the writer's version |
| SDD | `test_first` option (needs `checks`, default off): a tests loop with its own gate, then `implement` with `start_from: test_writer` | Chosen in the interview. It joins 13.4's fail-to-pass to tests a person approved and the team cannot change |
| Who is not checked | A person's edits at a gate, and the engine's own commits (`repo.commitArtifacts`, gate edits, integration merges) | A person decides (principle 3). The engine's commits are declared in the spec, not chosen by an agent |
| Order of work | Spec and validation, then tools, engine, evidence, SDD, API and web, in one PR | Chosen in the interview, as 13.3 and 13.4 were |
| Real run | Read step by step in the console with **GitHub Copilot** as the provider | Chosen in the interview. This is a one-off deviation from lessons rule 1's wording, recorded in the PR as 13.4 did. Rule 1 stays as it is |

## Open questions

- **`Directory.Build.props` in the defaults** may block legitimate work: it often holds build properties as well as analysis settings. The default keeps it protected; a workflow allows a node to change it.
- **Analyzer settings inside a `.csproj` and suppressions in code** are not caught here. The default lists them in the PR as a known gap that 13.6's reviewers cover. An alternative is a later evidence detail that counts new suppressions in the diff.
- **New test files and `conftest.py` written by the implementer** are allowed. A `conftest.py` that skips a frozen linked test makes the test skipped, so its criterion is `untested` and the work goes back (13.4). The default allows them; a workflow can protect `**/conftest.py`.
- **An approved test that already passes on the base** makes its criterion `not_proven`. The team cannot change the test, so the work goes back until the rounds run out and a person decides. The default keeps this and tells the test writer that its tests must fail now. An evidence check at `approve_tests` could come later.
