# AC-2 end-to-end: a canvas flow with parallel, orchestrator, loop and gate

Roadmap phase: 6.8
Branch: plan/6.8-ac2-canvas-end-to-end

## Context

AC-2 (product spec, US-3): "A user builds a flow with parallel, orchestrator, loop and gate on the canvas, and the run matches the drawn graph." Every part exists: `parallel` (4.1), the canvas and its edits (5.2–5.6, 6.6 `wrap`), the flow layout (5.9), `orchestrator` with replan and an integration branch (6.1–6.3), its tasks in the monitor (6.4), an orchestrator inside a loop (6.9) and gates (1.7, 6.7). No test has yet put them together: drawn by a person from a blank canvas, run, and checked against what was drawn. 6.8 is that proof. It is the last phase of Milestone 6 and closes AC-2 in the acceptance criteria map.

The engine's nesting rules fix the flow's shape: a gate may not be in a loop or a parallel, and an orchestrator may not be in a parallel (`models.py`: `loop_issues`, `parallel_issues`, `orchestrator_issues`). So the flow is a sequence:

```
explore (parallel: code_analyst | test_analyst)
  → review_loop (loop, max 3: implement (orchestrator, worker engineer) → synthesizer → reviewer)
  → approve_pr (gate on the integration branch's diff)
  → publish (github.openPR)
```

The user chose to ship this flow as a built-in template as well, so AC-2's flow is also something a team can start from the gallery. Principles that drive it: 1 (one spec, many views: the canvas, the run map and the run read one spec), 3 (the PR is behind a gate), 6 (every step that ran is visible where it was drawn), 7 (a thin, demonstrable slice). Lessons rules 1–6 apply to the template's agents.

## Scope

### In scope

- **Template `plan-build-review`** ("Plan, build and review"), in `agentic_engine.templates`, requires Claude and GitHub, with a required, named `input` (lessons rule 3):
  - `explore`: a `parallel` (join `all`) of two read-only analysts with the repo read tools: `code_analyst` maps the code the request touches, `test_analyst` finds the tests and how to check the change.
  - `review_loop`: a `loop` (`until` the reviewer's `verdict == "ok"`, `max_iterations` 3) over `implement` (an orchestrator: a lead with `hub.tools` read tools, worker `engineer` with the read and write tools, `max_workers` 2, `replan` once), `synthesizer` (read tools, writes the PR description) and `reviewer` (read tools, typed `verdict` / `feedback`).
  - `approve_pr`: a gate on the integration branch's diff; `publish`: `github.openPR` from `implement`, after the gate.
  - Options kept small: the models (`analyst_model`, `engineer_model`, `reviewer_model`, unset = workspace default, set = a priced model) and `max_passes` (1–3, default 3).
  - Instructions follow "Rules for writing workflows": each says what its input is and what its tools read.
- **A "run matches the graph" check** (`agentic_engine.conformance`, a test and eval helper, no API): given a workflow version's spec and a run's events, it lists every mismatch:
  1. every node an event names is a node of that spec (or a task of an orchestrator in it), tagged with the item, branch, iteration or task it ran in;
  2. every drawn node has an outcome: it ran (with its status), was not on the route taken, or was not reached because the run stopped (with where);
  3. order follows the spec: a sequence's steps in order, a parallel's branches all start after it starts and end before it ends, a loop's iterations numbered from 1, every iteration's steps in order;
  4. the run names the workflow id and version it ran, and that is the version checked.
- **The same check in the browser e2e**: the canvas cards of the version that ran and the run map's cards are the same ids at the same places, and each run map card has the status the events give it.
- **Gaps found while building the flow on the canvas or reading its run map** are fixed in this phase (each one a small task added to `plan.md` with a test when found).

### Out of scope

- A product view of the check (a "matches its graph" badge or API): the run map already draws the run on the version's spec. Evals (17.1) may reuse the helper later.
- Lifting the nesting rules (a gate in a loop, an orchestrator in a parallel): not needed for AC-2.
- A router after the loop as in the `team-review-pr` fixture: the gate prompt says when the loop ran out of passes; the router stays the fixture's.
- Drag and drop on the canvas: edits stay menu items (5.2).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| What 6.8 delivers | A template, a conformance check and two end-to-end proofs (engine, browser) | The user's choice: AC-2 proven and the flow reusable from the gallery |
| Flow shape | `parallel → loop(orchestrator → synthesizer → reviewer) → gate → openPR` | The only order the nesting rules allow with all four primitives and a PR behind a gate (principle 3) |
| Where the check lives | `agentic_engine.conformance`, used by tests (and later evals), no endpoint | The monitor already draws runs from the version's spec; the check proves it, it is not a feature |
| How the browser e2e builds the flow | From Blank canvas, by menu items only (Add a step after, Wrap in…, Replace with…, side panel), keyboard path included | AC-2 says "builds on the canvas"; starting from a stored spec would not prove it |
| Order of work | Engine check first, then the browser e2e, then the template's real run | The user's choice: the check defines "matches" before the UI is tested against it |
| Template vs fixture | A new template; `team-review-pr` stays an engine fixture | The fixture tests the router after a loop; the template is AC-2's flow with a parallel in front |

## Open questions

None left. Answered while building:

- **Does the lead see the request after the parallel?** No, and not in a later pass either: a looped hub's input is the review. Decided: the run's request is in every agent's context (`RunContext.request`, tech-stack → Agent runtime; lessons rule 8).
- **"At the same place"** means the same cards joined by the same edges. Grid cells may differ, since a sequence wraps to its pane's width, which differs between the canvas and the run map.
- **The e2e stack's fake agents only echoed,** so no orchestrator could run there. Decided: `FakeRuntime(fit_schemas=True)` in the worker's fake runtime (tech-stack → Agent runtime).

As first written:

- **Does the lead see the request after the parallel?** Its input is the parallel's output (the analysts' answers), and `RunContext` tells agents the repo but not the request. Group 1 checks it with a "what agents receive" test. If the request is lost, the choice is between the analysts each writing an artifact the lead `reads` with the request restated, or the run's request added to `RunContext` for every agent (a wider change, which would need its own lessons entry and tech-stack line). Decided in group 1, recorded in tech-stack before the template is written.
