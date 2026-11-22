# Plan: Evidence pack at the gate

## 1. Spike: test runners offline (findings first)
- [ ] Pick sample repos: two Node (one Jest, one Vitest; npm and pnpm), two Python (pytest with uv.lock, and requirements.txt), one .NET (xUnit). Add a failing-test variant of each.
- [ ] For each one, in job containers from the current sandbox image: restore on the registry network (13.2's commands), then build and test on `none` from `<staging>/.cache`. Record the exact commands, where the results land (JUnit / TRX / output only), the time each step takes, and what fails offline.
- [ ] Settle the open questions: how to get Node test counts, the test timeout, and how to detect pytest.
- [ ] Write `specs/2026-11-22-evidence-pack-gate/findings.md` and add decisions-log rows for each choice made.

## 2. Work copy from a writer's branch
- [ ] `agentic_sandbox.refs`: an `archive(ref, dest)` helper (`git archive` of `agent/<run>/<node>` into a directory under the staging directory, root-owned checkout untouched).
- [ ] `agentic_tools.build.workdir`: build the work copy from the archive when `node` is given, with the same pruning of package sources as 13.2.
- [ ] `scan.lint` takes an optional `node` (same archive, same `ReadableWriters` resolution and the same three refusal texts as 13.1).
- [ ] Tests in `packages/tools/tests` and `packages/sandbox/tests` (run single files, never the whole sandbox suite: memory note): branch tree used, checkout untouched, works after a restore.

## 3. `build.test` tool and test report
- [ ] `agentic_tools.build.tests`: runner detection per module (from the spike), and the build and test job commands for npm/pnpm/yarn, uv/pytest and `dotnet test`.
- [ ] Parse JUnit and TRX into `failures`. Cap them (20 failures, 500 characters per message), and map failures to the fixed reasons.
- [ ] `TestReport` model + `schemas/tests.v1.json`. Add `test` to `BuildLimits`.
- [ ] Register `build.test` in `BUILD_TOOLS` and the build server. Add it to the tool node manifest (palette). `tool_node_only` refuses it on an agent.
- [ ] Docker tests on fixture repos (Node, Python, .NET; each passing and failing): a test that reaches the network fails, and the checkout is unchanged after.

## 4. Evidence policy, step and send-back (engine)
- [ ] Spec: add `GateEvidence` to `GateNode` (`node`, `path`, `checks`, `max_rounds`) in `agentic_engine/spec/models.py`, and export it to JSON Schema.
- [ ] Validation: `evidence_not_in_loop`, `evidence_unknown_writer` and `invalid_evidence` in the validator, plus the existing sandbox and repo rules for `build.` tools. Add the browser's mirror if the canvas checks it live (5.6).
- [ ] Compiler: insert a hidden `<gate>:evidence` step before the gate. It calls `build.test` and `scan.lint` (base cached per `base_sha`, then branch) through the tool executor, builds an `EvidencePack` (`agentic_engine/evidence.py`, `schemas/evidence.v1.json`), writes the `evidence_collected` event and the `<gate>.evidence.json` artifact.
- [ ] Gate (`agentic_engine/gate.py`): if a required check failed and rounds are left, complete with `{decision: "changes", source: "checks"}` and comments from the failures (through `changes_text`), without an interrupt. Otherwise, pause with `evidence` and `rounds_left` in `gate_request`. Rounds come from the event log, like `_pass`.
- [ ] Store and audit: `gate_decided.source`, the audit action `gate.sent_back_by_checks`, `pending_gate` and `GET /runs/{id}/gate` return `evidence`. No migration if this fits in the event payloads; otherwise the next Alembic number.
- [ ] Engine tests (fake runtime):
  - A failing test sends the writer back with the failures in its next input, and no gate pause happens.
  - A pass reaches the gate with the pack.
  - When rounds run out, the gate pauses with the failing pack.
  - A worker restart between the evidence step and the gate does not run the jobs twice.
  - Assert what the writer receives (lessons, rule 1).

## 5. Web: evidence at the gate
- [ ] Regenerate the API client. Build `EvidenceStrip` in the gate review feature folder: `StatStrip` + `StatTile`s, `StatusBadge` per check, `Duration` for test time, `TruncatedPath` for files, and a list of failing tests (mono font for test names).
- [ ] Show it in the approval dock's review, the Inbox review and the review sheet, beside the diff. Add Loading, Empty and Error states.
- [ ] Console: the gate step's output shows the pack, and a send-back pass is labelled "Sent back by checks" in the step list.
- [ ] Side panel: edit `evidence` from the gate manifest's JSON Schema.
- [ ] Component tests. Add e2e for a gate with a passing pack and with a failing pack at 375 and 1440 px, light and dark, plus axe.

## 6. Templates, specs and the real run
- [ ] `plan_build_review.py` and `sdd.py`:
  - Add an evidence gate in the build's review loop (move the gate into the loop's body if it sits after it).
  - Make the writers' instructions name failing checks as a possible input.
  - Template tests and the AC-2 conformance check stay green.
- [ ] tech-stack: Tool layer (`build.test`, `scan.lint {node}`), Gate review (`evidence`, `source: "checks"`), UI design system (gate review shows the evidence strip), decisions-log rows from requirements.md.
- [ ] Docs and changelog: `docs/security/security-model.md` (test jobs offline), the roadmap 13.3 row's `[Plan](...)` link, and a `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] Real run on **GitHub Copilot** (8.2 personal connection) on a real Node or Python repo, read step by step in the console:
  - The writer's change breaks a test, and the run sends it back with the failures.
  - The writer fixes it, and the gate shows build, tests and analyzers.
  - Record anything that goes wrong in `specs/lessons.md`.
