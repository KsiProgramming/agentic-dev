# Validation: Protect the grader

## Done when (from roadmap)
> An implementer told to make the tests pass cannot change them; its attempt is shown at the gate and counted on the run

## Automated checks

- [ ] **Matcher (`packages/runtime`)**: `**`, `*` and `?`; case variants; `./` and backslashes; `..` and absolute paths refused; a default glob matches at any depth.
- [ ] **Repo tools (`packages/tools`)**:
  - `write_file` refuses a default, a workflow and a frozen path, each with its fixed text, and writes nothing;
  - `commit` refuses a staged protected path, including one written through a symlinked directory and both sides of a rename, and commits nothing;
  - an allowed node writes its paths;
  - an orchestrator task gets its orchestrator's rules;
  - every refusal calls `refused` once.
- [ ] **Validation**: `invalid_protect`, `allow_unknown_writer`, `protected_change_without_gate`, `start_from_unknown_writer`, `start_from_without_gate` and `start_from_not_allowed`, each with an actionable message; `test-first.json` validates.
- [ ] **Engine (fake runtime, `test_protected_paths.py`)**:
  - the implementer's request is asserted: its branch holds the test writer's files, its context has "# Protected paths" listing them with the approving gate, and it has the write tools (lessons 1);
  - a scripted write to a frozen test is refused, the branch is unchanged, `protected_path_refused` is written, the gate's `gate_waiting` lists the attempt, and the run's count is 1;
  - an orchestrator with `start_from`: the hub's first read sees the tests, and every task's branch starts from them;
  - the gate's `changes` lists the started writer's files once, marked protected;
  - a restart before, during and after the branch is started, a restore from saved bundles and a rerun from a step all keep the start point and the frozen set (lessons 7);
  - 13.3's and 13.4's evidence tests pass unchanged.
- [ ] **Evidence with the base's config (Docker fixtures, run by file; never `packages/sandbox/tests` as a whole)**: a change that turns off a ruff rule in `pyproject.toml`, and one that silences a .NET rule in `.editorconfig`, still report the base's findings as new. The checkout and the writer's worktree are unchanged after.
- [ ] **Templates**:
  - both SDD builders with `test_first` on and off;
  - `test_first` without `checks` is refused;
  - the tests assert what `test_writer`, the lead and an engineer receive;
  - AC-5, the spec-file test and the 7.6 follow-up pass;
  - "Plan, build and review", Docs and Audit still validate with the platform defaults.
- [ ] **API** (run from `packages/api`): `protected_attempts` on `GET /runs` and `GET /runs/{id}`; `GET /runs/{id}/gate` with attempts and `changes[].protected`.
- [ ] **Web unit**: `protected-attempts.test.tsx` (attempts, none, loading, error), the "Protected" mark in the gate's files, the Input tab's list, the refused call's one-liner, and the header tile shown only above zero.
- [ ] **Web e2e on the rebuilt compose stack**: the gate review with attempts in the dock, the Inbox and the review sheet; `layout.spec.ts` at 375, 768 and 1440 px and `a11y.spec.ts` (axe), in light and dark. Run them here, not only written.
- [ ] `uv run` lint, strict type check and tests; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.
- [ ] `git status --short` lists every new file, and a clean clone of the branch imports and tests (lessons 12).

## Manual / demo checks

- [ ] **Real run on GitHub Copilot.** Run "Build from a spec file" with `checks` and `test_first` on, on a real Python or .NET repo, with Copilot as the provider and the starter's personal connection (8.2, 8.3). Use a spec with at least three `AC-` criteria. Read it step by step in the console's Activity tab:
  - `test_writer` writes tests named with each criterion's id, in test files only, and `approve_tests` shows them;
  - the lead's first turn reads the approved tests on the integration branch, and its Input tab lists them as protected;
  - the engineers make them pass without changing them; any attempt is refused with its fixed text and shown in Activity;
  - the final gate shows the tests marked protected in the diff, the attempts (if any), and the criteria proven by "fails before → passes after";
  - the run's header shows the count when there were attempts.

  If no engineer tries to change a test, the PR says so and points to the engine and e2e tests for the refusal. Anything wrong goes into `specs/lessons.md`.
- [ ] Look at the gate review and the console against the real stack at 375 and 1440 px, in light and dark (lessons 11).
- [ ] Read the event log: each refusal is one `protected_path_refused` with its rule, and no event carries file contents.

## Merge criteria

- [ ] All automated checks above pass in CI.
- [ ] `findings.md` (group 4's spike) is committed, with a decisions-log row for each choice it made.
- [ ] These land in this PR:
  - tech-stack: Tool layer, Agent runtime, Gate review, Workflow validation, UI design system → Gate evidence, SDD template, the platform's default list and the decisions log;
  - design-language, if a neutral badge was added;
  - the roadmap (13.5's plan link and the `test_first` note);
  - `docs/security/security-model.md`;
  - the `CHANGELOG.md` entry.
- [ ] The PR says the real run used GitHub Copilot instead of Claude, a one-off deviation from lessons rule 1, and links the run.
- [ ] The PR lists the known gaps: analyzer settings inside a `.csproj` and suppressions in code (left to 13.6), and `Directory.Build.props` being protected by default.
- [ ] Refusal texts and events name paths and rules only. No file content or secret reaches an event, an artifact or a log.
