# Evidence pack at the gate

Roadmap phase: 13.3
Branch: plan/13.3-evidence-pack-gate

## Context

Today a gate shows a diff, and the approver has to judge it alone. Whether the change builds, whether the tests pass and whether the analyzers found something new is left to them, or to CI after the PR is open. 13.3 makes the platform collect that evidence before a person looks (Milestone 13, principles 2 and 3). The roadmap row says a failing check sends the work back to the writer, and a passing change reaches the gate with its checks shown.

It builds on:
- **4.4 and 4.8, the scanners**: `scan.lint` and its findings report with fingerprints (4.5).
- **13.2, package egress**: `build.restore`, job containers on `npm`, `pypi` and `nuget`, and package caches in `<staging>/.cache/<manager>`. 13.2 left two items to this phase: running the tests, and building a writer's branch instead of the checkout.
- **13.1, reading a writer's work**: reads with `node` go through git refs (`agentic_sandbox.refs`), so they still work after a restore (12.2).
- **7.8, request changes**: a gate in a loop's body can complete as `decision: "changes"`. The comments then become the loop's next input for the writer.

It unblocks:
- 13.4: coverage and fail-to-pass join the same pack and the same policy.
- 13.6: independent review reads the evidence pack.
- 16.1, 16.2, 16.4 and 18.6: their build and test loops.
- 19.2, 19.7 and 19.8: they add checks to the pack.

What drives the design:
- **Principle 2 (safe by construction).** The checks are deterministic tool calls run by the engine. They are never an agent's claim, and they are never an agent's tool.
- **Principle 5 (repo content is data).** Test names and failure messages are repo output. They reach the writer as data, capped, under a fixed heading.
- **Principle 8 (calm UI, truthful numbers).** The gate shows the pack as one `StatStrip`, with status shown through `StatusBadge`.
- **tech-stack "Build tools (13.2)"** and its decisions-log rows. This phase keeps the same rules: no repo code runs while the network is up, failure reasons are fixed phrases, tool nodes only, and jobs never run in the checkout.

## Scope

### In scope

- **`build.test {node?, path?, ecosystems?: "auto" | ["node", "python", "dotnet"]}`.** It joins `BUILD_TOOLS`, so only a tool node may call it (`tool_node_only` refuses it on an agent).
  - It builds and tests the tree of a writer's branch (`node`, resolved through `ReadableWriters` as in 13.1), or the checkout when `node` is not given.
  - The work copy comes from `git archive` of the branch's ref, not a worktree, so it also works after a restore.
  - Per module, a restore job runs on the registry's network with scripts off (the writer may have added a package). A build job and a test job then run on `none`.
  - It returns a test report (`schemas/tests.v1.json`), one check per module: `path`, `ecosystem`, `runner`, `status` (passed / failed / skipped / error), `reason`, `build` (ran / failed), `passed`, `failed`, `skipped`, `failures` (at most 20: `name`, `file`, `message` of at most 500 characters), `test_ms`, plus `counts` and `truncated`.
- **Test runners come from the repo**, settled by the spike in plan group 1:
  - Node: the `test` script in `package.json`. npm's placeholder `no test specified` counts as no script.
  - Python: pytest, when the project depends on it or configures it.
  - .NET: `dotnet test` on the test projects.
  - Results are read from JUnit or TRX files where the runner writes them, otherwise from the exit code with no counts.
- **Fixed reasons, never the tool's words**:
  - `no tests found`
  - `tests failed (N of M)`
  - `does not build`
  - `test run timed out`
  - `no supported test runner for <lang>`
  - 13.2's restore reasons, unchanged
- **`scan.lint` on a writer's branch**: an optional `node` argument, with the same `git archive` work copy.
- **The evidence policy on a gate**: `evidence: {node, path?, checks: {build, tests, analyzers}, max_rounds}`.
  - `build` and `tests` are `required`, `shown` or `off`.
  - `analyzers` is `no_new` (fails on any finding whose fingerprint is not in the base's report), `shown` or `off`.
  - `max_rounds` is how many times the checks may send the work back (at least 1).
  - The shape leaves room for 13.4's `coverage` and `criteria`.
- **Evidence is its own checkpointed step.** The compiler puts a hidden `<gate>:evidence` step before a gate that has `evidence`. It runs `build.test` and `scan.lint` (on the base and on the branch) as tool calls. It records an `evidence_collected` event and a `<gate>.evidence.json` run artifact (`schemas/evidence.v1.json`: one entry per check with `kind`, `status`, `required`, `summary` and `detail`).
- **Send-back through 7.8's request-changes path.**
  - When a required check fails and rounds are left, the gate does not pause. It completes with `{decision: "changes", source: "checks"}`, and the failures become comments (`## Tests`, `## Build`, `## Analyzers`, through `changes_text`). The loop's next pass hands those comments to the writer.
  - No approval row is written. `gate_decided` carries `source: "checks"`, and the audit log records `gate.sent_back_by_checks`.
  - When rounds run out, the gate pauses and shows the failing pack. A person then decides.
- **Validation** for `evidence`:
  - The gate must be in a loop's body (`evidence_not_in_loop`).
  - `node` must be a writer, or an orchestrator whose body writes, that runs before the gate in that body (`evidence_unknown_writer`).
  - `max_rounds` must be below the loop's `max_iterations` (`invalid_evidence`).
  - At least one check must be on (`invalid_evidence`).
  - A sandbox and a repo are required (the existing rules for `build.` tools).
  - The canvas side panel edits the block from its JSON Schema (5.4).
- **The gate's API**: `gate_waiting` and `GET /runs/{id}/gate` carry `evidence` (the pack and `rounds_left`). The engine passes the latest pack to the gate request.
- **Web**:
  - An `EvidenceStrip`: one `StatStrip`, one `StatTile` per check, the status shown through `StatusBadge`, and the failing tests listed under it. It appears in the approval dock's review, the Inbox review and the gate's review sheet, beside the diff.
  - In the console, the gate step shows its pack, and a pass sent back by checks reads "Sent back by checks" in the step list.
  - The three states (loading, empty, error) come from `@/components/states`.
- **Templates**:
  - "Plan, build and review" and SDD get an evidence gate in the build's review loop. Build and tests are required, analyzers `no_new`, `max_rounds: 3`.
  - Where the template's gate sits after the loop, it moves into the loop's body. The AC-2 conformance check (6.8) still passes.
  - The writers' instructions say that their input may be failing checks (lessons, rules for writing workflows).
- **Specs and docs**: tech-stack (Tool layer, Gate review, UI design system for the gate review, decisions log), the roadmap row's plan link, `docs/security/security-model.md` (test jobs run offline) and `CHANGELOG.md`.

### Out of scope

- Coverage thresholds and fail-to-pass per acceptance criterion: 13.4. Only the policy's shape is left open for them.
- Protecting the tests from the writer: 13.5. A writer can still edit a failing test until then. The PR says so.
- pass^k and mutation scores: they stay in `ideas.md`.
- A self-check inside the agent's own loop (`ideas.md`, "agent harness"): the graph's evidence step is this phase.
- Go, Rust and Java tests: no restore for them yet (13.2).
- Showing the refused egress hosts in the console: 10.2 or 13.7.
- Evidence on a gate outside a loop. Such a gate has nowhere to send the work back, so it is refused, not given a "show only" mode. A tool node writing a test report covers that case.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | The full row plus a declarative evidence policy on the gate | Chosen in the interview. Authors declare which checks must pass instead of wiring a loop condition by hand, and 13.4 adds its thresholds to the same block. |
| How failing work goes back | The gate completes as 7.8's `decision: "changes"` with `source: "checks"`, and the failures become comments | It reuses the path that already hands comments to the writer's next pass, so there is no second send-back mechanism. The send-back is visible in the event and audit logs, and no approval row pretends a person decided. |
| Where the checks run | A hidden `<gate>:evidence` step, checkpointed before the gate | LangGraph runs a node again from the start when it resumes after `interrupt()`. Running the jobs inside the gate node would run them twice. A step of its own also survives a worker restart (AC-8). |
| When rounds run out | The gate pauses and shows the failing pack | The run neither loops forever nor fails silently. Principle 3 leaves the call to a person. |
| What is built | The writer's branch, through `git archive` of its ref | The same refs as 13.1's reads, so it works after a restore and shows only committed work. The checkout and the worktrees are never touched (4.8's rule). |
| `build.test` callers | Tool nodes and the evidence step, never agents | Its restore opens a route out of the sandbox (13.2's row "build.restore is for tool nodes only"). |
| Analyzers `no_new` | Compare finding fingerprints between the base and the branch | Fingerprints already match the same issue across runs (4.4, 4.5). A repo with old lint debt can still pass. The base's report is cached per run (`runs.base_sha`). |
| Order of work | Spike, then the tool, then the gate and policy, then the web, then templates and a real run | Chosen in the interview. 13.2 showed that a spike on real repos settles what the docs do not (lessons, rule 10). |
| Real run | Read step by step in the console, with **GitHub Copilot** as the provider instead of Claude | The user's choice. Since 8.3 the same workflow runs on both providers unchanged (AC-6). Lessons rule 1 and the roadmap note say "Claude", so the PR records this deviation (see Open questions). |

## Built differently from the plan

What changed while building it, and why (decisions-log rows in tech-stack, lessons rules 12 and 13):

- **A gate with `evidence` takes no `on_changes`.** The plan let both exist. A person's request for changes is counted by pauses and the checks' send-backs are not, so together they could send the loop's last pass back and end it unapproved. The checks send back, and a person approves or rejects.
- **The last pass is never sent back.** `rounds_left` is `min(max_rounds - used, passes left)`, on top of `max_rounds` below the loop's `max_iterations`. The plan's `max_rounds: 3` for a 3-pass template was itself invalid.
- **The template adopts evidence by option.** "Plan, build and review" takes `checks` (default off) and `check_rounds`; with `checks` its gate moves into the loop's body. The build-from-Jira templates are unchanged: their `commit_specs` step must stay in the root sequence before the gate, so a gate in the loop needs its own design. Default flows, AC-2's conformance and `on_review` follow-ups are as they were.
- **The hidden step is `<gate>.evidence`**, not `<gate>:evidence`, as every other internal node id uses a `.`.
- **`scan.lint {node}` and `build.* {node}` run the existing scripts in the extracted tree** (`agentic_tools.tree.TreeSandbox`) instead of through job containers, so the scanners and the build are unchanged.
- **Not done:** the Docker fixture tests, the e2e run, the spike on real repos and the real Copilot run. See `findings.md`.
- **Found on the way:** 13.2's whole `build` package was never committed, as `.gitignore` has `build/` (lessons rule 12).

## Open questions

- **Test result counts for Node.** Jest, Vitest and node:test each need a JUnit reporter to write results, and that reporter may not be in the lockfile. The spike decides between three options: a reporter flag the runner already has, counts read from its output, or exit code only.
- **Lessons rule 1 wording.** This phase's real run uses Copilot. Should rule 1 and the roadmap note say "a real provider (Claude or Copilot)" from now on, or is this a one-off exception recorded in the PR? The default is a one-off exception.
- **Test job timeout.** 600 s, like the build, unless the spike's sample repos need more.
