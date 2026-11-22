# Later steps read the writers' work

Roadmap phase: 13.1
Branch: plan/13.1-writers-work-readable

## Context

Each writer commits on its own branch, `agent/<run>/<node>` (1.6). The nodes after it read the run's checkout, which is the code as the run found it. Only an orchestrator's integration branch is read by the nodes after it (6.9, [lessons](../lessons.md) rule 5). So a reviewer after a test writer and a refactoring writer, in a plain sequence, reviews code that holds neither change. The first place anyone sees the work is the gate.

13.1 is the first phase of Milestone 13, which the roadmap's "Next up" line names after Milestone 8 (now done). The evidence pack (13.3), the independent review (13.6) and the circuit breakers (13.7) all assume that a later step can read what a writer changed.

It depends only on finished work: writer branches (1.6), integration branches (6.3, 6.9), saved and restored branches (12.2: a resumed run's fresh sandbox gets the branches back) and provider selection (8.3: the same tools run on Copilot).

What drives it:

- **Mission principle 4**, tools live in the platform. The new tool and arguments belong to the `repo` server, so Claude and Copilot see the same thing.
- **Principle 5.** A diff is repo content: data, never instructions.
- **Principle 6**, transparency. The console shows which writers a step was told about and what it read.
- **Lessons rules 1, 4 and 5.** Trace what each agent receives. An agent that judges code can read it. A new way of producing or reading work says what the nodes after the writer read.

## Scope

### In scope

- **`repo.diff {node, path?}`**, a new read tool. It returns the files the writer `node` changed against the run's base, with status, path and lines added and removed (binary files are named, not shown), then the unified diff (`-M`). The result is cut at 256 KB (`RepoLimits.max_bytes`, the same cap as `artifacts.read`), with a note to call again with `path` to see one file.
- **`node` on `repo.read_file`, `repo.list_files` and `repo.search`.** With `node`, these read the writer's branch as last committed. They read it from git refs (`git show`, `git ls-tree`, `git grep`), never from a worktree. Without `node`, they read as they do today.
- **What `node` names:** a writer node, or an orchestrator whose body writes (its integration branch). A task key such as `implement.t1` is not accepted, because the integration branch is the team's work.
- **Who may pass `node`:** every agent with the repo read tools. That covers read-only agents, hubs and writers (a refactorer can read the tests the test writer added). A writer that passes its own id reads as it would without `node`.
- **Only writers that completed before the step can be read.** Any other `node` is refused with one of three fixed messages: `'x' is not a writer of this run`, `writer 'x' has not run before this step` or `writer 'x' has no commits`.
- **Each step is told which writers ran before it.** For every agent with repo read tools, a "# Work before you" section follows the run's context. It gives each writer's id, role and kind of branch, explains how to read it with `node`, says that only committed work is visible, and says what reads without `node` return. The section is not part of the step's input, so typed ports and `input_schema` checks are unchanged.
- **`node_started` carries the writers.** For an agent-like node it has `writers: [{node_id, kind: "writer" | "integration"}]`, and the console's Input tab lists them.
- **`repo.diff` joins `READ_TOOLS`.** So it is in the agents' tool list, in the palette and side panel through the manifests and in hub tools; it is allowed in loops, maps and parallels; and it needs a repo.
- **Validation issue `no_writer_before`** on a node granted `repo.diff` when no writer runs before it in run order. A loop body's writers count for the whole body, since later iterations follow them.
- **The console's Activity tab draws a `repo.diff` result as a unified diff.** File headers sit on `surface-subtle`, and the `+` and `−` markers stay so colour is never the only cue. New diff tokens cover light and dark. `repo.diff` and reads with `node` get their own one-liners.
- **A fixture workflow for "Done when"**, `review-two-writers.json`: `test_writer` → `refactorer` (reads the new tests with `node`) → `reviewer` (`repo.diff` on both writers, typed `verdict`).
- **Specs:** in `tech-stack.md`, the Tool layer, the Agent runtime's "What an agent is told" and decisions-log rows; in `design-language.md`, the diff tokens; and a `CHANGELOG.md` entry.

### Out of scope

- **Granting `repo.diff` to the reviewers of the existing templates** (plan-build-review, SDD). It changes what their agents receive, so each would need its own real run. 13.6's independent review gets the diff by construction.
- **Uncommitted work** in a writer's worktree.
- **Task writer keys as `node`.**
- **Starting a writer's branch on top of an earlier writer's branch.** Test-first flows with frozen tests are 13.5.
- **Why each hunk was written**, which is 14.2.
- **A new Playwright spec.** The existing e2e suite, with its axe and layout checks, still runs.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How a step learns which writers ran | A "# Work before you" section after the run's context, plus `node_started.writers` | The input stays the previous step's output, so typed ports do not change. The engine writes the section from the run's state, never from model output, as it does `RunContext` |
| How a writer's work is read | From the git refs `agent/<run>/<node>` in the checkout | It works after a restore (12.2), when there is no worktree. It reads only committed work, which is what a gate and a PR see. A reader can never write through it |
| Which writers a step may read | The writers that completed, worked out from the checkpointed state (`order`, `results`, `integrated`). The engine hands the list to the worker's repo tools through a `ReadableWriters` object, the same pattern as `BranchSaver` and `GateReview` | Writers cannot run inside maps or parallels, so the list only grows, and every step running at the same moment gets the same one. Working it out from state gives a resumed run the same answer. The 6.9 reroute (readers that call as an orchestrator) leaves it unchanged |
| What the diff is against | The run's base: the clone's `HEAD`, `runs.base_sha` | It is the base a gate's review and 12.3's changes use. An orchestrator in a loop shows all of its iterations |
| Diff cap | 256 KB (`RepoLimits.max_bytes`), with `path` to see one file | This is the roadmap's "artifact cap", the same as `artifacts.read` and `repo.read_file` |
| Writers reading earlier writers | Allowed, read-only | Your choice. A refactorer that has to keep the new tests passing needs to read them |
| Listing and searching a writer's branch | `node` on `list_files` and `search` as well as `read_file` | Your choice. A reviewer can browse and search the changed code, not only the files it already knows |
| Diff colours | New tokens `--diff-added`, `--diff-removed` and their `-muted` backgrounds, in light and dark, written into `design-language.md` and `tech-stack.md` before they are used | CLAUDE.md rule 1 allows colour from tokens only. A diff line is not a status, so it does not borrow the status hues (design-language keeps severity apart from status for the same reason) |
| `no_writer_before` | A blocking issue | Validation has no warnings, and a tool that can never return anything is a mistake in the workflow |
| Real run | On Copilot, through the 8.2 personal connection, not on Claude | Your choice. The roadmap's "Done when" names no provider. The PR says that this run stands in for the Claude run in lessons rule 1 |

## Open questions

- Copilot asks permission once per custom tool ([lessons](../lessons.md) rule 10), and its adapter grants the platform's tools. The real run confirms that `repo.diff` and the `node` argument go through unchanged.
- The roadmap's "Next up" line still says Milestone 8 at 8.1. Following CLAUDE.md, it moves to "Milestone 13 at 13.1" in its own small PR, not in this one.
