# Validation: `parallel` primitive with join policies (all/any/quorum)

## Done when (from roadmap)
> Three branches run concurrently and join correctly

## Automated checks
User choice: the proof is engine tests on the fake runtime plus spec and validation tests. The engine tests use LangGraph's `InMemorySaver` and need no network and no database.

- [ ] `test_spec.py`:
  - The three `valid/parallel-*.json` fixtures validate.
  - Each `invalid/parallel-*.json` is rejected, and the error names its code (`schema`, `not_allowed_in_parallel`, `not_allowed_in_loop`, `not_allowed_in_map` or `policy_limit`), its node and its path.
  - The exported JSON Schema has `parallel` with `branches` from 2 to 8 items and `join` as `all`, `any` or `quorum`.
- [ ] `test_validate.py` (API): `POST /workflows/{id}/validate` returns `200` with `not_allowed_in_parallel` for a gate in a branch. It returns `policy_limit` (`agents_alive`) for 4 branches under a workspace limit of 3. `POST /runs` refuses the same spec with `422`.
- [ ] `test_parallel.py`, Done when:
  - Three agent branches run, and the fake runtime's peak in flight is 3.
  - The `all` join completes.
  - The output holds the three outputs in branch order, even though the branches finished in reverse.
- [ ] `test_parallel.py`, join policies:
  - `any` completes on the first branch to complete and cancels the others.
  - `any` fails only when every branch fails.
  - `quorum: 2` of 3 completes at 2 completed branches, and fails once 2 have failed. Either way it cancels the rest.
  - `all` fails fast on one failure, naming the branch, and cancels the others.
  - Cancelled branches end `node_cancelled` and appear in `data.cancelled`.
- [ ] `test_parallel.py`, limits:
  - Too many agents in the branches fail the parallel before any branch starts (`agents_spawned`).
  - With `agents_alive` at 2, the peak is 2 and all branches still finish.
  - A budget stop inside a branch ends the run with `policy_limit_exceeded` (`budget_usd`), not as a sibling cancel.
- [ ] `test_parallel.py`, events:
  - One `node_started` and one end event for the parallel.
  - One `parallel_branch_started` and one `parallel_branch_completed` per branch.
  - Body events carry `payload.branch`.
  - `seq` runs 1..n with no gaps.
- [ ] `test_parallel.py`, state:
  - Branch node results are in `results`, and a later CEL condition reads one.
  - The run's usage sums every branch.
- [ ] `test_parallel.py`, resume: after a cut-off once branch 0 has finished, `resume_workflow` runs only branches 1 and 2, and the join is correct (AC-8).
- [ ] The existing engine, store, API, worker, sandbox and web suites still pass. Tests change only where the `Node` union or the timeline and graph shapes widened.
- [ ] `ruff check`, `ruff format --check`, strict `pyright`/`mypy`, ESLint, Prettier and `tsc` are clean.
- [ ] CI is green, including the Playwright screenshots and axe checks that already exist.

## Manual / demo checks
User choice: a live run on docker compose.
- [ ] `docker compose up`, then start a run with `valid/parallel-three-reviewers.json` on Claude, using the template's start flow or `POST /runs`.
  - On the Timeline, three branches run at once, each nested with its own messages.
  - The graph tab shows the parallel box with three side-by-side branches, its header moving to "3 of 3 branches · all", and every node Done.
- [ ] Run `valid/parallel-any.json`:
  - One branch completes.
  - The others show "Cancelled" in the timeline and the graph.
  - The run's text is the winner's output.
  - The run's cost covers only the tokens actually spent.
- [ ] Kill the worker mid-parallel (`docker compose restart worker`). The run resumes, finished branches do not run again, and the run completes.
- [ ] At 375 px the graph tab has no horizontal page scroll, and a branch node opens its detail sheet.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The JSON Schema, the OpenAPI spec and `schema.d.ts` are re-exported. The README "Parallel" section, tech-stack.md (run console, validation codes, decisions log) and the CHANGELOG are updated.
- [ ] Branches hold only `agent`, `tool` and `sequence` nodes, and none is a gate, a writer or a publisher. No custom CEL functions are added.
- [ ] The roadmap phase 4.1 is marked done in the PR.
