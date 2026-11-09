# Ideas

A parking lot for ideas that are not on the roadmap yet. Capture them here quickly, refine them later, and promote them to `roadmap.md` once they are clear enough to become a phase (then plan them with the `plan-feature` skill).

Status: `💡 Raw` just captured · `🔍 Refining` being shaped · `📋 Ready` clear enough to become a phase · `➡️ Promoted (phase X.Y)` moved to the roadmap · `🗑️ Dropped` decided against (keep a one-line reason).

---

## Template

Copy this block to add an idea. Only the title and the problem are needed to start.

```markdown
### <Short title>

- **Status:** 💡 Raw
- **Added:** YYYY-MM-DD
- **Problem:** what is missing or painful today, and for whom
- **Idea:** the rough solution, if any
- **Open questions:** what needs deciding before it can be a phase
- **Links:** issues, PRs, discussions, related phases
```

---

## Backlog

### User-authored tools, published for flows and agents

- **Status:** 💡 Raw
- **Added:** 2026-10-23
- **Problem:** Agents can only call the platform's own MCP servers (`repo`, `github`, `jira`, …). A team that needs its own tool, such as an internal API, a custom linter or a deploy check, has no way to add it and reuse it.
- **Idea:** A user creates a tool (name, description, input/output JSON Schema, plus an implementation: an HTTP endpoint, a container, or an MCP server they host). They test it, then publish a version to the workspace. Once published it can be used in two places: as a `tool` node in a flow, and in an `agent` node's tool grants so the agent can call it. A tool registry would list tools with their versions, owners and the permissions they declare.
- **Already covered:** 10.1 *Plugin nodes* (a manifest plus a container/HTTP endpoint in its own sandbox) covers a code node in a flow, but not a tool an agent calls. 6.6 sets the draft → published versioning pattern, but only for composites. The mission says users extend the platform with plugin nodes, and tech-stack says tools are granted per node through the node manifest.
- **Open questions:** Does one manifest describe both a plugin node and an agent tool? How are third-party code and its credentials sandboxed, given that agents never see credentials? Is a tool scoped to a workspace or shared across workspaces? Who may publish? Does a write tool need a gate? It has to behave the same on Claude and on Copilot (principle 4).
- **Links:** roadmap 1.6, 5.3, 6.6, 10.1, 10.2

### Skills usable in flows and agents

- **Status:** 💡 Raw
- **Added:** 2026-10-23
- **Problem:** Know-how such as "how we write ADRs", "our PR conventions" or "how to upgrade a .NET project" gets pasted into node instructions again and again. Nothing reuses it or versions it.
- **Idea:** A skill is a published, versioned package: instructions, plus optional reference files, scripts and the tools it needs. It is attached to an `agent` node, which loads the skill when the task matches, or used as a flow step. Skills live in a workspace registry next to templates and tools. Agent Skills (`SKILL.md`) may be a fitting format.
- **Already covered:** Nothing directly. The closest are 6.6 composites (reusable subgraphs, not reusable know-how) and 9.9 promoting a flow to a template.
- **Open questions:** Is the format portable across Claude and Copilot (AC-6)? Can a skill bring its own tools (see the idea above)? How does it get into the sandbox? Can the Flow Architect find skills, maybe as a `list_skills` tool next to 9.2? Do bundled scripts need the same trust controls as plugins?
- **Links:** roadmap 6.6, 8.3, 9.2, 9.9

### Repo healer: continuous maintenance agent

- **Status:** 💡 Raw
- **Added:** 2026-10-23
- **Problem:** Repos drift: dependencies get outdated, security advisories pile up, deprecated APIs and syntax remain, lint debt grows. The audit template (4.6) reports once, but nothing keeps a repo healthy over time.
- **Idea:** A "Heal repo" template, or an agent run on a schedule. It scans for package updates, vulnerabilities (CVEs, secrets) and outdated or deprecated syntax. It groups and ranks the findings, then opens issues for things that need a human decision and fix PRs (behind a gate) for safe fixes, such as a dependency bump with passing tests or an automated syntax migration. It avoids duplicate issues and PRs across runs.
- **Already covered:** 4.4 deterministic tool nodes (linter, dependency scanner, secret scanner), 4.6 the read-only "Audit codebase" template, and 6.7 turning selected audit findings into fix PRs. Missing: scheduled or recurring triggers (today runs start only manually or from a Jira or GitHub webhook), a `github` tool to create issues, package-update detection and fixes, and dedupe against existing issues and PRs or Dependabot.
- **Open questions:** A schedule trigger (cron per repo) as its own phase? Does creating an issue go through a gate (the mission lists push, PR, repo creation and Jira changes)? Should it work alongside Dependabot/Renovate or replace them? How do we keep it from flooding a repo with PRs (batching, budget, max open PRs)?
- **Links:** roadmap 4.4, 4.6, 6.7, 7.3, 7.6

### Upload a Markdown file instead of writing definitions by hand

- **Status:** 💡 Raw
- **Added:** 2026-10-23
- **Problem:** Every definition is filled in by hand: a run's input or description, a workflow spec, and the manifests of tools, skills and plugin nodes (names, descriptions, JSON Schemas, parameters). Teams usually already have this written down in Markdown (a feature spec, a README, an ADR, a `SKILL.md`) and have to type it all again.
- **Idea:** Anywhere a description or definition is asked for, the user can upload or paste a `.md` file:
  - **Run input:** the file becomes the description or spec the agents receive, for example the spec an SDD run implements, without going through Jira.
  - **Workflow:** the Flow Architect reads the file as the goal and drafts the graph, so the user reviews a draft instead of building it from scratch.
  - **Tool / skill / plugin definitions:** an agent extracts a draft manifest (name, description, inputs/outputs schema, parameters) from the file. The user reviews and edits it in the form before publishing. A `SKILL.md` can be imported almost as it is.
  The extracted definition is always shown as an editable draft that passes validation. Nothing is published straight from the file.
- **Already covered:** In part. 9.4 turns a plain-language goal into a draft (typed text, not a file). 7.4–7.5 feed Jira fields to the spec writer. 5.4 generates the side-panel forms from JSON Schema. There is no file upload, and no extraction of a manifest from Markdown.
- **Open questions:** Where does the uploaded file live: a run artifact (4.3), a stored version, or both? The content is untrusted data, never instructions (principle 5), so how is it shown and quoted to agents? What are the size limits, and can a file reference images or other files? Should a file from the repo also be accepted (e.g. `docs/spec.md`), not only an upload?
- **Links:** roadmap 4.3, 5.4, 7.4, 7.5, 9.4; the tool and skill ideas above

### Workflows that work on several repos

- **Status:** 💡 Raw
- **Added:** 2026-11-02
- **Problem:** A run works on exactly one repo: `POST /runs` takes `repo` or `new_repo`, the sandbox clones that one checkout, and every `repo.*`, `scan.*` and `github.*` call acts on it. A team cannot draw "agent A studies the API repo, agent B studies the web repo, a third agent combines their findings", which is common for cross-service changes, audits and migrations.
- **Idea:** A run takes named repos (`repos: {api: …, web: …}`) and a node picks one (`repo: "api"`); a node with none uses the first. The sandbox clones each into its own folder; the repo tools act on the node's repo; each writer's branch and pull request target its own repo, and each still passes a gate. The fan-in already exists: a `parallel` of agents, then a `reduce` (`agent`, `dedupe` or `vote`). The run sheet asks for each repo, the side panel gets a repo picker per node, and the console shows which repo a step worked on.
- **Already covered:** Nothing. 6.5 `subflow` calls another workflow, but on the parent's repo. 4.5 merges findings from several sources within one repo.
- **Open questions:** Does a workflow declare the repo roles it needs (like a template's parameters), or does the run name them freely? One sandbox with several checkouts, or one sandbox per repo? How do the GitHub App's installation and repo access apply per repo? How does the Flow Architect (9.x) choose repos? Must it behave the same on Copilot (AC-6)?
- **Links:** roadmap 4.5, 6.3, 6.5, 9.x; seen while testing 5.8 on GildedRoseKata

### Publish a stored workflow as a template

- **Status:** 💡 Raw
- **Added:** 2026-11-02
- **Problem:** Saving a workflow in the builder makes a new version (5.1), listed under Workflows (5.8), but never a template: templates are Python code (`agentic_engine.templates`) served read-only by `GET /templates`. A tech lead who builds a good flow cannot offer it on the start screen to the rest of the team, although the mission names "publishing templates" as the tech lead's entry point.
- **Idea:** "Publish as template" on a stored version: a name, description, icon, the connections it requires (worked out from the spec, as `workflowRequires` does), and which parameters a user fills in when starting it (for example an agent's instructions or a list of paths). The template is stored per workspace, versioned (draft → published, as 6.6 does for composites), and shown in the gallery beside the built-in ones; updating it publishes a new version.
- **Already covered:** In part. 9.9 promotes highly rated flows to templates automatically (the Architect's learning loop), not on a user's request. 6.6 sets the draft → published pattern for composites. 5.2 opens a template in the builder, the other direction.
- **Open questions:** How are a template's parameters bound to the spec (JSON paths, as `setParam` uses)? Workspace-only, or shared across workspaces? Who may publish? Do built-in templates move to the same storage?
- **Links:** roadmap 5.1, 5.2, 5.8, 6.6, 9.9; mission "Who we serve"

### Later agents can read what earlier writers changed

- **Status:** 💡 Raw
- **Added:** 2026-11-02
- **Problem:** Each writer commits in its own worktree and branch (`agent/<run>/<node>`); a later agent has only the base checkout. A reviewer agent placed after a test writer and a refactoring writer cannot read either branch, and their replies are not kept unless the spec gives them `writes`. Only the gate's review sheet shows the diffs, to the human. Testing 5.8, a review agent guessed artifact names and reviewed nothing.
- **Idea:** Give agents read access to the run's writer branches: `repo.diff {node}` (the files a writer changed and the diff against its base) and `repo.read_file {path, node}` to read a file as a writer left it. Optionally, a writer's final reply is kept as an artifact by default (`<node>-report.md`). The node's input says which writers ran before it.
- **Already covered:** In part. 6.3 merges worker branches into an integration branch before the final PR, which a later agent could then read. 3.6 and the gate review sheet show the diffs to the approver. 4.3 artifacts carry what a spec declares with `writes`.
- **Open questions:** Is this enough once 6.3 exists, or still needed between writers in sequence? Read-only for every later agent, or only for ones granted it? How large may a diff be before it is cut (the 256 KB artifact cap)?
- **Links:** roadmap 3.6, 4.3, 6.3, 6.4

### Recover runs lost between the queue and the worker

- **Status:** 💡 Raw
- **Added:** 2026-11-02
- **Problem:** A worker pops a run id from Redis, then claims the run in Postgres. If it crashes between the two, or while parsing the stored spec (seen on 2026-11-02: a worker older than 5.4 could not parse `budget_usd`), the id is gone from the queue and the run has no lease, so `reclaim_expired_run` never sees it. The run stays "Queued" for good, and the console shows "Waiting for the run to start…" with nothing to explain why.
- **Idea:** Treat Postgres as the queue's source of truth: on startup and on a timer, the worker re-enqueues runs that have been `queued` with no lease for longer than a threshold. A run that fails to load (a spec this worker cannot parse) is failed with a clear `failure_reason` rather than crashing the worker. The console could show "Queued for N min" and a hint once that passes the threshold.
- **Already covered:** In part. Leases and `reclaim_expired_run` (1.3) resume only runs a worker stopped mid-way, not runs it never claimed. Rerun (2.6) lets a user start over by hand.
- **Open questions:** Is a version check between API and worker (refusing to claim a spec from a newer schema) needed as well? What threshold avoids re-enqueuing a run another worker is about to claim? Should the API, not the worker, do the sweep?
- **Links:** `agentic_worker.main._next_run`, `agentic_store.lease`; principle 9 (nothing is lost)

### Commit trailers that link a change back to its run

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** A commit the platform pushes says nothing about where it came from. Once a PR is merged, the link from the code to the run that wrote it (workflow, version, node, approver, cost) lives only in our database. Someone reading `git log` or `git blame`, or a team that stops running the platform, loses it.
- **Idea:** Every commit the platform makes (a writer's commit, an approver's edits, the integration branch) carries git trailers: `Agentic-Run: <run_id>`, `Agentic-Workflow: <id>@v<version>`, `Agentic-Node: <node>` and, for edits made at a gate, `Agentic-Approved-By: <user>`. `git log --format='%(trailers)'` then gives the run of any line of code, and the console links back from a run id. Entire's Checkpoints CLI does the same with an `Entire-Checkpoint: <id>` trailer.
- **Already covered:** Nothing. Commits are made in the sandbox (`agentic_sandbox.review.commit_files`, the repo write tools) with plain messages; the PR body (1.8) links the run, but only on GitHub and only for the PR as a whole.
- **Open questions:** Which ids are safe to publish in a public repo (a run id is harmless; an approver's name or email may not be)? Should the PR body list the same trailers? Do squash merges on GitHub keep them (they keep the PR body, not each commit's trailers)?
- **Links:** roadmap 1.6, 1.8, 6.3; mission "Traceable delivery"; [Entire Checkpoints](https://docs.entire.io/guides/checkpoints/overview)

### Show why each change was made beside the diff at the gate

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** The gate's review sheet shows the diff, but not why the agent wrote it. To check a hunk, the approver has to leave the review, find the right agent turn in the console and match it to the file by hand. Review is the slow, risky step once agents write the code.
- **Idea:** Each diff hunk in the review links to the agent turn and tool call (`repo.write_file`, …) that last wrote it, with the agent's short note or reasoning for that turn shown inline or on hover. The events log already has every tool call with its node, turn and arguments; the work blocks (11.8) already render turns. Entire builds its product on this point: agent sessions reviewed as artifacts beside the code.
- **Already covered:** In part. 3.6 and the editable gate artifacts show and edit the diff; 11.8 shows agent turns as work blocks in the console. Nothing joins the two.
- **Open questions:** How is a hunk matched to a write when several turns touch the same file (last write wins, or every turn listed)? How much reasoning is shown, given that not every provider streams it? Is the reasoning untrusted text to render as such (principle 5 and rule 11)? Same view on Copilot (AC-6)?
- **Links:** roadmap 1.7, 3.6, 11.5, 11.8; principle 6 (transparency)

### Rerun from a node, with the code as it was there

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Rerun (2.6) starts a run over from the first node. When a long flow (an SDD run, an audit with fixes) goes wrong at its last step, the user pays again for every step before it. The checkpointer (1.3) resumes a run that stopped, but nothing lets a user go back to a node and try it again, for example with changed instructions.
- **Idea:** After each node, the run keeps a snapshot of the state and of the code (the writer branches' commits are enough while writes go through git). The console offers "Rerun from here" on a node: a new run starts from that node's checkpoint, with the code restored, optionally with edited node parameters, and links to the run it came from. Entire's `rewind` restores code to an earlier checkpoint of an agent session in the same way.
- **Already covered:** In part. 1.3 durable execution keeps a checkpoint after each node; 2.6 reruns a whole run; 5.7 runs any version of a workflow. 7.6 (a review comment resumes the run) and 9.8 (runtime adaptation at checkpoints) need the same mechanism.
- **Open questions:** A new run or a new attempt within the same run (history and cost reporting differ)? Which edits are allowed from a checkpoint: parameters only, or the graph after the node (a new workflow version)? How long are checkpoints and branches kept? What about effects outside the sandbox that already happened (a pushed branch, a Jira comment)?
- **Links:** roadmap 1.3, 2.6, 5.7, 7.6, 9.8; principle 9 (nothing is lost)

### Keep a run's record in the repo itself (opt-in)

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** The audit trail of a run (workflow version, prompts, tool calls, cost, approvals) lives only in the platform's Postgres. A team that moves deployments, loses its database or stops using the platform loses the story behind its code, and auditors must be given access to the platform to see it.
- **Idea:** As an opt-in per workspace or workflow, the platform writes a short run record (JSON plus a readable summary) to an orphan branch of the repo, such as `agentic/runs/v1`, which shares no history with the code and holds only metadata. Commit trailers (idea above) point into it. Entire stores its checkpoints the same way, on an `entire/checkpoints/v1` orphan branch, so code branches stay clean.
- **Already covered:** Nothing. The events log (0.5) and audit log view (3.7) keep everything, but only in the platform.
- **Open questions:** Writing to the repo is a write action: does it go through a gate, or is approving the PR enough? What is left out (secrets never; prompts and repo content may be sensitive in a public repo)? Size limits for long runs? Does it conflict with branch protection rules?
- **Links:** roadmap 0.5, 3.7, 10.5; principles 3 and 6; mission v1 decision "open source, self-hosted first"; the commit trailers idea above

### Measure how much of a change people edited before approving

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Approvers can edit a writer's diff at the gate, but nobody can see how often or how much. That number is the plainest signal of agent quality per workflow, node and provider, and 9.10 needs an "edit distance" metric for the Flow Architect.
- **Idea:** When a gate is approved, record for each file the lines the agent wrote, the lines a person changed, and the lines kept as written. Show a share per run (a `StatTile` and `Percent` in the console) and per workflow over time. Entire attributes lines to agents or people per checkpoint for the same purpose.
- **Already covered:** In part. Editable gate artifacts (3.6) commit the approver's edits on the writer's branch, so the data exists in git; nothing counts it.
- **Open questions:** Lines or characters? Do edits after the PR is opened (on GitHub) count? Is the number shown to every user, or only in workspace metrics?
- **Links:** roadmap 3.6, 9.9, 9.10; mission "How we measure success"

### Read Entire checkpoints when profiling a repo

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Many teams will commit code written with other agents (Claude Code, Copilot, Cursor). When those teams use Entire's open-source Checkpoints, their repo already holds why that code was written, but our agents never see it.
- **Idea:** The RepoProfile builder (9.1) notices `Entire-Checkpoint` trailers and the checkpoint metadata branch, and offers a read-only tool (`repo.history_context {path}`) that returns the recorded intent behind the code an agent is about to change. The content is data, never instructions (principle 5).
- **Already covered:** Nothing.
- **Open questions:** Is Entire's metadata format stable and documented enough to depend on (it has already moved from one branch to one ref per checkpoint)? Worth it before many repos use it? Same tool for our own run records (idea above)?
- **Links:** roadmap 9.1, 9.2; [Entire Checkpoints](https://docs.entire.io/guides/checkpoints/overview)

### Host repos ourselves (a forge for agents)

- **Status:** 🗑️ Dropped
- **Added:** 2026-11-09
- **Problem:** Entire (2026) is building a Git forge for agent-written code, which raises the question of whether we should host repos too.
- **Idea:** None; recorded so it is not raised again.
- **Reason dropped:** GitHub is the v1 host and other hosts come later as adapters (mission non-goals); a forge is a different product. We integrate with forges instead.
- **Links:** mission "Non-goals (v1)"
