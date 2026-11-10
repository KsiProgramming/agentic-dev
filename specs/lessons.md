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

## Rules for writing workflows and templates

- **Name the input.** Declare `input` (label, example) when the first step works on a request; mark it `required` when the workflow cannot do anything without it (rule 3).
- **Say what each agent receives.** Instructions start with what the input is ("Your input is the engineers' reports for all the work so far") and what the tools read ("your tools read the code with that work in it"). Never "Your input is the repository".
- **Give read tools to every agent that checks code:** the lead (`hub.tools`), the synthesizer, the reviewer (rule 4).
- **No placeholder instructions.** "Describe what this agent does." is the builder's starter text: a step that still has it does not know what to do.
- **Review loops:** the reviewer answers a typed `verdict` (`ok` / `changes`) and `feedback`, the loop's `until` reads `results.reviewer.data.verdict`, and the publish stays after the loop, behind a gate.
- **Run it for real once.** Before a workflow is shared or made a template, run it with Claude on a real repo and read each step's Activity: every agent should have read what it needed, and each step's answer should be what the next one needs.
