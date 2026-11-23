# Plan: Protect the grader

One PR, in this order. The tree keeps working after each group, with one behaviour change: once group 2 lands, the platform defaults are enforced for every writer. `start_from` and `test_first` change nothing until a spec uses them.

## 1. Spec, matcher and validation (`packages/runtime`, `packages/engine`)

- [ ] `agentic_runtime.paths`: one glob matcher on repo-relative normalised paths (`**`, `*`, `?`, case-insensitive), reusing `repo_relative`'s rules (no `..`, no absolute paths). Unit tests cover `./`, backslashes, case variants, `**` at the start, middle and end, and a dotfile at any depth.
- [ ] `PLATFORM_PROTECTED` in the engine (the CI and analyzer-config globs from requirements), with a docstring that says why each is there.
- [ ] `ProtectPolicy` (`paths`, `allow: dict[NodeId, list[glob]]`) on `WorkflowSpec`. `start_from: NodeId | None` on `AgentNode` and `OrchestratorNode`.
- [ ] Validation issues, each with an actionable message:
  - `invalid_protect`: an empty or malformed glob, or one that leaves the repo;
  - `allow_unknown_writer`: a node that is not a writer;
  - `protected_change_without_gate`: an allowed node with no gate after it, before the next writer that starts from it or the next publish;
  - `start_from_unknown_writer`: not a writer, the node itself, or one that does not complete before it;
  - `start_from_without_gate`;
  - `start_from_not_allowed`: in a map or a parallel.
- [ ] Regenerate the JSON Schema and node manifests, so the canvas side panel edits `start_from` (5.4). The workflow's `protect` is edited where its other top-level fields are; if there is no such place, it is JSON only, and the PR says so.
- [ ] Validation tests in the engine's spec tests, and valid and invalid fixtures under `packages/engine/tests/fixtures/specs/`.

## 2. Refusal in the repo tools (`packages/runtime`, `packages/tools`)

- [ ] `ProtectedPaths` in `agentic_runtime.tools`, beside `ReadableWriters`:
  - `rules_for(node_id)` returns each pattern with where it came from: default, workflow, or frozen with its writer and gate;
  - `refused(node_id, tool, path, rule)` is called back for each refusal;
  - task keys (`fix.t1`) take their orchestrator's rules.
- [ ] `build_repo_server(protected=…)` and `open_repo_tools(protected=…)`, passed to every writable server, task writers included.
- [ ] `repo.write_file` checks the normalised path before `put_file`. `repo.commit` lists the staged paths (`git diff --cached --name-only -z -M`, both sides of a rename) and refuses the whole commit if any is protected, leaving the worktree as it is. Each refusal uses one fixed text per rule:
  - `'<path>' is protected by the platform (CI and analyzer config): you can read it but not change it`;
  - `… by this workflow (<pattern>) …`;
  - `… approved at <gate> from <writer> …`.
- [ ] Tests in `packages/tools/tests`: each refusal text; nothing is written or staged; a write through a symlinked directory is refused at commit; a rename out of a protected path is refused; an allowed node writes; readers are unchanged.

## 3. Engine: rules per step, `start_from`, events and what agents receive (`packages/engine`, `packages/sandbox`, `packages/worker`)

- [ ] The engine sets `ProtectedPaths` before every step, as it sets `ReadableWriters`. The rules come from the spec (`PLATFORM_PROTECTED`, `protect.paths` minus `allow`) and the checkpointed state (frozen files).
- [ ] `start_from` in `agentic_sandbox`, next to `start_branches`: make the node's branch at the earlier writer's tip, before the node's first turn. For an orchestrator this means its integration branch, so the hub reads it and tasks start from it.
  - Integration's "empty" check uses that start point, not the clone's `HEAD`.
  - The frozen set is `git diff --name-only <base>..<start tip>` through `agentic_sandbox.refs`, stored in `RunState` with the start sha and the gate that approved it.
- [ ] 12.2 and 12.4: saved bundles carry the started branch; a resume, a restore and a rerun from a step keep the start point and the frozen set. Tests cut off before, during and after the branch is started (lessons 7).
- [ ] The gate's `changes` (`agentic_engine.gate`):
  - an entry that matches a protected path carries `protected` and `rule`;
  - a writer that a later writer started from is shown inside the later writer's diff, not on its own;
  - the diff of a started writer stays against the run's base, so the PR's whole change is shown.
- [ ] The `protected_path_refused` event in `agentic_engine.events` and the worker's sink, written from the `refused` callback with the step's attempt.
- [ ] `protected_text` (beside `work_before_text`) writes the "# Protected paths" section for every writer, capped (patterns, then up to 50 frozen files and "and N more"). `node_started` carries `protected: {patterns, frozen, frozen_from, gate}`.
- [ ] Lessons 5: test what the nodes after a started writer read. The gate shows the started writer's branch, a reviewer's `repo.diff` names it, and the hub reads the integration branch from its first turn.
- [ ] Engine tests on the fake runtime, `test_protected_paths.py`:
  - the implementer's request (its tools, its context with "# Protected paths", its branch holding the tests) is asserted, not only the outcome (lessons 1);
  - a scripted write to a frozen test is refused, writes the event and leaves the branch unchanged;
  - the attempt appears in the gate's `gate_waiting` and in the run's count;
  - a worker restart keeps both.

## 4. Analyzers with the base's config (`packages/tools`)

- [ ] Spike first, on a real ruff repo and a real .NET repo (lessons 14), with the results in `specs/2026-11-23-protect-the-grader/findings.md`:
  - ruff with `--config` pointing at the base's `pyproject.toml` or `ruff.toml` for a module whose `[tool.ruff]` the change weakened;
  - the base's `.editorconfig` and `*.globalconfig` laid over a .NET tree, confirming the build reads them.
- [ ] `scan.lint {node, config: "base"}`: lay the base's copy of the analyzer-config files over the archived tree, using `agentic_tools.tree`'s overlay from 13.4, which adds, replaces and removes to match the base. Then pass ruff the base's config where a module's `pyproject.toml` changed `[tool.ruff]`. `config` without `node` is refused.
- [ ] `agentic_engine.evidence.collect` passes `config: "base"` on the change-side lint.
- [ ] Docker fixture tests in `test_scan_docker.py` or `test_build_docker.py`: a change that disables a ruff rule in `pyproject.toml`, and one that silences a rule in `.editorconfig`, still report the findings the base's config finds. Run them by file, never `packages/sandbox/tests` as a whole.

## 5. SDD `test_first` (`packages/engine/src/agentic_engine/templates/sdd.py`)

- [ ] `test_first: bool = False` on `SddFileParams`, refused without `checks`.
- [ ] `tests_loop` after `tasker`:
  - `test_writer`, a writer with the read tools, reading `spec.md`, `plan.md`, `tasks.md` and the gate's comments;
  - `approve_tests`, a gate with `on_changes: max_revisions` that writes the comments (`test-changes.md`), with a prompt that says what approving freezes.
- [ ] `implement` gets `start_from: "test_writer"`. The lead, engineer, tasker and reviewer instructions get a `_TEST_FIRST_*` addition: the approved tests are on your branch, you can read them, writes to them are refused and counted, make them pass unchanged, and say so if a test is wrong.
- [ ] Template tests assert what `test_writer`, the lead and an engineer receive (lessons 1) and that the spec validates with `test_first` on and off. AC-5's worker test and the spec-file test run with `test_first`. A 7.6 follow-up still starts at `review_loop`.

## 6. API (`packages/api`, `packages/store`)

- [ ] `protected_attempts` on `GET /runs` and `GET /runs/{id}`, counted from the run's `protected_path_refused` events (`agentic_store` summaries).
- [ ] `gate_waiting` and `GET /runs/{id}/gate` carry `protected_attempts: [{node_id, path, rule, count}]` (at most 50) and `changes[].protected` / `rule`.
- [ ] Regenerate the OpenAPI spec and the web client. API tests run from `packages/api`.

## 7. Web (`web/`)

Read `specs/design-language.md` and tech-stack → UI design system first.

- [ ] `ProtectedAttempts` (`web/src/runs/console/protected-attempts.tsx`): a writer's attempts at the gate, each with its path (`TruncatedPath`), the rule and the count. It appears in the approval dock's review sheet, the Inbox review and the review sheet, and only when there are attempts. It has the three states.
- [ ] `gate-files.tsx` marks protected files with a neutral "Protected" label and its rule, and no status colour. If design-language has no neutral badge, add one there and in tech-stack first.
- [ ] `run-tiles.tsx`: a "Protected files" tile with the run's count when it is above zero (no empty tiles).
- [ ] The Input tab lists a step's protected paths beside 13.1's writers (`step-input.tsx`). `tool-describe.ts` gives a refused write its one-liner ("Refused: tests/test_cart.py is protected").
- [ ] Component tests: `protected-attempts.test.tsx`, plus additions to `work-before.test.tsx` and `step-view.test.tsx`.

## 8. Fixture, specs and the real run

- [ ] `packages/engine/tests/fixtures/specs/valid/test-first.json` (see requirements).
- [ ] e2e on the rebuilt compose stack: a gate review with attempts and protected files, in the dock, the Inbox and the review sheet, at 375, 768 and 1440 px, in light and dark, with axe.
- [ ] Specs and docs:
  - tech-stack: Tool layer, Agent runtime, Gate review, Workflow validation, Gate evidence, SDD template, and decisions-log rows for each decision in requirements;
  - the roadmap: 13.5's plan link and the `test_first` note;
  - `docs/security/security-model.md`: protected paths, and the base config at the evidence step;
  - `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Real run on Copilot (see validation). Read it step by step, and add an entry to `specs/lessons.md` for anything tests did not catch.
