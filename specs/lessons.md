# Lessons from real runs

Mistakes that reached a real run, and the rule each one left. Read this before you change the engine (`packages/engine`, `packages/runtime`, `packages/tools`) or write a workflow or template. When a real run goes wrong in a way tests did not catch, add an entry in the same PR as the fix: what happened, the rule, and what now enforces it (a test, a validation, a default). A rule that matters more than once also goes into `tech-stack.md` (with a decisions-log row) or `mission.md`, where it is binding; this file is the record of why.

## Rules for the engine and the runtime

### 1. Trace what every agent sees, not only what the graph does
*From 6.9 (2026-11-10).* The fake-runtime tests were green while real `team-review-pr` runs went wrong three times: the lead had no tools, the reviewer read the wrong code, a synthesizer had nothing to say. Fake agents answer whatever their script says, so tests prove the graph's shape, never that an agent was given enough to do its job.

- For a feature that changes what flows between nodes, write down, for each agent of a real workflow (a template or `team-review-pr`): its instructions, its input, its tools, and which code those tools read (checkout, its own branch, an integration branch). Check it against what the agent is asked to do.
- Add an engine test that asserts what an agent *receives* (its request's input, tools, context, the node id its tool calls go out as), not only the run's outcome.
- A phase that changes agents' inputs or tools is not done until a real run with Claude on a real repo (`AGENTIC_RUNTIME=claude`) has been read step by step in the console's Activity tab.

### 2. The repo is context, not input
*From 6.9.* Agents saw only their instructions and their input; runs started with an empty input, or with the repo's name typed in, and the first agent did not know where it worked or what to do. Enforced by `RunContext` (every agent is told the repository) and the empty-input wording (`agentic_runtime.claude.user_turn`).

### 3. A workflow that needs a request says so
*From 6.9.* `team-review-pr` and `plan-execute-reflect` expect a request but the run sheet's input was optional and unnamed. Enforced by `input: {label, required, description, example}` on the spec, `POST /runs` (422) and the run sheet. Any template or stored workflow whose first step works on "the request" declares it.

### 4. An agent that must judge code can read it
*From 6.9.* An orchestrator's hub had no way to take tools and planned blind ("I could not read the repository"). Any agent asked to plan from, describe, or review code gets the repo's read tools (`repo.list_files`, `repo.read_file`, `repo.search`). Enforced for hubs by `hub.tools` (read tools only).

### 5. After work is merged, readers read the merged work
*From 6.9.* A reviewer after the team read the run's original checkout, found none of the merged work and rejected it, which forced a pass with nothing to do. Enforced by `_reads_as` / `_integrated_reader` in the compiler: once an orchestrator merged a task, later read-only nodes call their tools as that orchestrator, so they read its integration branch. A new way of producing work (a new writer kind, a new branch) must say what the nodes after it read, with a test.

### 6. An agent with no tools is told so
*From 6.9.* A tool-less synthesizer that wanted to check the repo wrote a pretend `<invoke name="repo.read_file">` as its answer, and the next step took it as the change. Enforced by `NO_TOOLS_INSTRUCTION`. Never let an agent's text answer be the only thing a later step receives without considering what it outputs when it cannot do its job.

### 7. "Nothing left to run" is not "the run ended"
*From 6.9.* A run cut off after a step's tasks had saved their results resumed as `completed` and skipped every node after it, because the checkpoint had no `next`. Enforced in `resume_workflow` (a checkpoint with pending tasks goes on) and its tests. When the engine decides from a LangGraph snapshot, check `tasks` as well as `next`, and test a cut-off at every point of a step: before, during and after its last task.

### 8. The request is context, like the repo
*From 6.8 (2026-11-10).* Writing AC-2's flow (two analysts in a parallel, then a lead in a review loop), the "what agents receive" test showed the lead never saw the request: a parallel passes on only its branches' outputs, and a looped hub's later input is the review. `team-review-pr` had the same gap from its second pass. Caught by a test before a real run, and recorded here because it changes what every agent receives. Enforced by `RunContext.request` (every agent is told the run's request, as data) and the tests in `test_ac2.py` and `test_orchestrator.py`. When a node's input is a container's output or a review, check that it still knows the goal.

### 9. A run that asks a question must wait for the answer
*From 7.5, found 2026-11-18.* The SDD template's `clarify` posted its open questions to Jira with `ask_jira` and the run went straight on to `tasker` and the build, on assumptions the team had not confirmed. The `post_questions` gate only asked whether to *post*; nothing waited for anyone to answer, and the spec (tech-stack, "Open questions in SDD") said so, so the spec was wrong, not only the code. The fake-runtime tests passed because they asserted that the comment was posted and that the pull request opened, and never asked what happens *after* `ask_jira`. Enforced by the `wait_for` step (7.9) and tests that assert the run holds after `ask_jira` with `tasker` not started, that only another person's comment (webhook or direct check) resumes it, that the platform's own comment does not, that the timeout ends the run, and that a restart mid-wait still waits.
- Any step that asks a person or a system for something must be followed by a step that waits for it; "asked" and "answered" are two events, and a test checks the time between them.
- For every outward write, ask what the run does next and whether it should have waited.
- **Who answers is not who is connected.** The first real run (7.9) never found the answer: the person who connected Jira answered from the connected account, and the check took every comment of that account for the platform's own. The platform's comments are now told by their footer (`Posted by agentic-dev run`), never by account; tests answer from the connected account (`test_an_answer_from_the_connected_account_still_resumes_the_run`). When a check tells "ours" from "theirs", test with the one-person team.

### 10. A new provider is built on a run, not on its documentation
*From 8.2 (2026-11-22).* The first reading of Copilot's SDK (docs and PyPI) said it reported no usage, left headless use unstated and did not say whether the app could be a company App. The first real call showed usage per call (tokens and AI credits, with the input count including cache reads and writes), headless use on a person's token and a permission request per custom tool; and it showed that an invalid token fails at `session.create` with a 401. An adapter written from the docs would have estimated usage and guessed the rest. Enforced by 8.2's order (a spike on a real account before the adapter, results in `specs/2026-11-18-copilot-sdk-terms/findings.md`) and by `SdkConnector`'s `translate`, tested on stand-ins shaped like the events the spike printed.

- Before an adapter for a provider, call it for real once with a token, a custom tool and an invalid token, and write down every event and field it returned.
- Map a refusal by its HTTP status to a fixed code, never by the provider's words (`failure` in `copilot.py`).
- A provider whose spike could not be run (no account, no subscription) is a conditional go at most.

### 11. The provider a run uses decides what it needs
*From 8.2.* Every unit test was green while the New run sheet still asked for a Claude key before it would start a Copilot run, so a workspace with only a Copilot subscription (which the mission allows) could not start one from the UI. Found by opening the sheet in a browser against a real stack. Enforced by `requiredFor` in `new-run-sheet.tsx` and the test "a Copilot run needs no Claude key".

- A checklist of connections is the template's requirements minus what the chosen provider does not use; never the template's list as it is.
- Look at the screen once against a real stack before calling a UI phase done: the rendered sheet showed what the component tests could not.

### 12. A package that git ignores is not in the pull request
*From 13.3 (2026-11-22).* 13.2 added `packages/tools/src/agentic_tools/build/`, the package that restores and builds a repo, and merged without it: the root `.gitignore` has `build/` (for build output), `git add` skipped the whole directory, and 13.2's CI was green only because the files existed on the author's machine. A fresh clone of `main` could not import `agentic_tools.build`. It was found when 13.3 changed those files and `git status` did not list them. Enforced by a negation in `.gitignore` (`!packages/tools/src/agentic_tools/build/`).

- After adding a package or a directory with a common name (`build`, `dist`, `lib`, `out`), check that git sees it: `git status --short` lists it, or `git check-ignore -v <file>` says nothing.
- A phase that adds source files is checked on a clean clone before it is called done, since a local tree can hide a file CI never gets.

### 13. A send-back must leave a pass to act on
*From 13.3.* A check that sends the work back to a writer ends a pass, and a loop that runs out of passes ends with the work unapproved, so whatever follows it (a publish) would run. The first design only required `max_rounds` below the loop's `max_iterations`, which holds on paper and fails as soon as another step also uses passes (a reviewer's `changes`, a person's request for changes). Enforced by `rounds_left = min(max_rounds - used, passes left in the loop)` (`_evidence` in the compiler), a test that reaches the last pass with a round unused (`test_the_checks_never_send_the_work_back_on_the_loops_last_pass`), and the refusal of `evidence` with `on_changes` on one gate.

- Anything that decides a loop goes round again must know how many passes are left, and never use the last one.
- When two mechanisms send work back, count them together, or keep them apart.

### 14. A test runner is built on a run, not on its documentation
*From 13.3 (2026-11-22).* `build.test` for .NET passed every unit test on a scripted sandbox, and its first run on a real repo found "no tests found": the project was not found (a `find` that prunes a start path named `.`), then the TRX files, which start with a byte-order mark, did not parse, then the test host could not start (tests built for net8.0, an image with one runtime, .NET 10), and zero tests read as "no tests found" instead of a failed run. Enforced by `DOTNET_ROLL_FORWARD=LatestMajor`, the byte-order-mark and zero-tests-with-a-failing-exit tests (`test_build_dotnet_test.py`), and the rule below.

- A job that wraps a tool is run once for real, on a real repo, before it is called done; scripted sandboxes prove the parsing, not that the tool ran.
- "Nothing found" and "could not run" are different answers: zero results with a failing exit code is the second.
- A report that says "nothing to build" for a repo in a language it does not handle hides the gap: say which languages were looked at.

### 15. A result named after the test is not there when the test cannot run
*From 13.4 (2026-11-22).* The first design of fail-to-pass read "failed before" from a linked test's failing result on the base. The spike showed pytest ends a run on an import error with one entry named after the *module* (`tests.test_new`), never the test, so a new test that cannot import the base's code has no result that holds its criterion's id. Enforced by deciding that a linked test is proven when it passes on the change and the base run does not report it as passed, and by the tests that give a base with no result and a base that does not build (`test_evidence_criteria.py`).

- When a check asks "did X fail", ask what the tool reports when X cannot run at all; absence of a pass is the answer a tool can always give.
- A later pass's input is not the check text alone: a looped hub receives `{input, iteration, previous}`. A test that asserts what a writer receives reads that shape (caught before a real run by `test_sdd_checks.py`, and the lead's instructions say `input`, not "your input").

## Rules for writing workflows and templates

- **Name the input.** Declare `input` (label, example) when the first step works on a request; mark it `required` when the workflow cannot do anything without it (rule 3).
- **Say what each agent receives.** Instructions start with what the input is ("Your input is the engineers' reports for all the work so far") and what the tools read ("your tools read the code with that work in it"). Never "Your input is the repository".
- **Give read tools to every agent that checks code:** the lead (`hub.tools`), the synthesizer, the reviewer (rule 4).
- **No placeholder instructions.** "Describe what this agent does." is the builder's starter text: a step that still has it does not know what to do.
- **Review loops:** the reviewer answers a typed `verdict` (`ok` / `changes`) and `feedback`, the loop's `until` reads `results.reviewer.data.verdict`, and the publish stays after the loop, behind a gate.
- **Run it for real once.** Before a workflow is shared or made a template, run it with Claude on a real repo and read each step's Activity: every agent should have read what it needed, and each step's answer should be what the next one needs.
