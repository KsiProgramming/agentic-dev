# Ideas

A parking lot for ideas that are not on the roadmap yet. Capture them here quickly, refine them later, and promote them to `roadmap.md` once they are clear enough to become a phase (then plan them with the `plan-feature` skill).

Status: `💡 Raw` just captured · `🔍 Refining` being shaped · `📋 Ready` clear enough to become a phase · `➡️ Promoted (phase X.Y)` moved to the roadmap · `🗑️ Dropped` decided against (keep a one-line reason). `➡️ Promoted in part (phases X.Y)` names the phases that took part of an idea and says what stays here. An idea that needs a change to `mission.md` before it can become a phase keeps its status and gets a **Parked** line that says which principle or scope it goes against.

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

- **Status:** ➡️ Promoted (phase 15.4)
- **Added:** 2026-10-23
- **Problem:** Agents can only call the platform's own MCP servers (`repo`, `github`, `jira`, …). A team that needs its own tool, such as an internal API, a custom linter or a deploy check, has no way to add it and reuse it.
- **Idea:** A user creates a tool (name, description, input/output JSON Schema, plus an implementation: an HTTP endpoint, a container, or an MCP server they host). They test it, then publish a version to the workspace. Once published it can be used in two places: as a `tool` node in a flow, and in an `agent` node's tool grants so the agent can call it. A tool registry would list tools with their versions, owners and the permissions they declare.
- **Already covered:** 10.1 *Plugin nodes* (a manifest plus a container/HTTP endpoint in its own sandbox) covers a code node in a flow, but not a tool an agent calls. 6.6 sets the draft → published versioning pattern, but only for composites. The mission says users extend the platform with plugin nodes, and tech-stack says tools are granted per node through the node manifest.
- **Open questions:** Does one manifest describe both a plugin node and an agent tool? How are third-party code and its credentials sandboxed, given that agents never see credentials? Is a tool scoped to a workspace or shared across workspaces? Who may publish? Does a write tool need a gate? It has to behave the same on Claude and on Copilot (principle 4).
- **Links:** roadmap 1.6, 5.3, 6.6, 10.1, 10.2

### Skills usable in flows and agents

- **Status:** ➡️ Promoted (phase 15.3)
- **Added:** 2026-10-23
- **Problem:** Know-how such as "how we write ADRs", "our PR conventions" or "how to upgrade a .NET project" gets pasted into node instructions again and again. Nothing reuses it or versions it.
- **Idea:** A skill is a published, versioned package: instructions, plus optional reference files, scripts and the tools it needs. It is attached to an `agent` node, which loads the skill when the task matches, or used as a flow step. Skills live in a workspace registry next to templates and tools. Agent Skills (`SKILL.md`) may be a fitting format.
- **Already covered:** Nothing directly. The closest are 6.6 composites (reusable subgraphs, not reusable know-how) and 9.9 promoting a flow to a template.
- **Open questions:** Is the format portable across Claude and Copilot (AC-6)? Can a skill bring its own tools (see the idea above)? How does it get into the sandbox? Can the Flow Architect find skills, maybe as a `list_skills` tool next to 9.2? Do bundled scripts need the same trust controls as plugins?
- **Links:** roadmap 6.6, 8.3, 9.2, 9.9

### Repo healer: continuous maintenance agent

- **Status:** ➡️ Promoted (phases 18.1, 18.2, 18.4)
- **Added:** 2026-10-23
- **Problem:** Repos drift: dependencies get outdated, security advisories pile up, deprecated APIs and syntax remain, lint debt grows. The audit template (4.6) reports once, but nothing keeps a repo healthy over time.
- **Idea:** A "Heal repo" template, or an agent run on a schedule. It scans for package updates, vulnerabilities (CVEs, secrets) and outdated or deprecated syntax. It groups and ranks the findings, then opens issues for things that need a human decision and fix PRs (behind a gate) for safe fixes, such as a dependency bump with passing tests or an automated syntax migration. It avoids duplicate issues and PRs across runs.
- **Already covered:** 4.4 deterministic tool nodes (linter, dependency scanner, secret scanner), 4.6 the read-only "Audit codebase" template, and 6.7 turning selected audit findings into fix PRs. Missing: scheduled or recurring triggers (today runs start only manually or from a Jira or GitHub webhook), a `github` tool to create issues, package-update detection and fixes, and dedupe against existing issues and PRs or Dependabot.
- **Open questions:** A schedule trigger (cron per repo) as its own phase? Does creating an issue go through a gate (the mission lists push, PR, repo creation and Jira changes)? Should it work alongside Dependabot/Renovate or replace them? How do we keep it from flooding a repo with PRs (batching, budget, max open PRs)?
- **Links:** roadmap 4.4, 4.6, 6.7, 7.3, 7.6

### Upload a Markdown file instead of writing definitions by hand

- **Status:** ➡️ Promoted (phases 7.7, 9.11, 15.5)
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

- **Status:** ➡️ Promoted (phases 19.1, 19.2)
- **Added:** 2026-11-02
- **Problem:** A run works on exactly one repo: `POST /runs` takes `repo` or `new_repo`, the sandbox clones that one checkout, and every `repo.*`, `scan.*` and `github.*` call acts on it. A team cannot draw "agent A studies the API repo, agent B studies the web repo, a third agent combines their findings", which is common for cross-service changes, audits and migrations.
- **Idea:** A run takes named repos (`repos: {api: …, web: …}`) and a node picks one (`repo: "api"`); a node with none uses the first. The sandbox clones each into its own folder; the repo tools act on the node's repo; each writer's branch and pull request target its own repo, and each still passes a gate. The fan-in already exists: a `parallel` of agents, then a `reduce` (`agent`, `dedupe` or `vote`). The run sheet asks for each repo, the side panel gets a repo picker per node, and the console shows which repo a step worked on.
- **Already covered:** Nothing. 6.5 `subflow` calls another workflow, but on the parent's repo. 4.5 merges findings from several sources within one repo.
- **Open questions:** Does a workflow declare the repo roles it needs (like a template's parameters), or does the run name them freely? One sandbox with several checkouts, or one sandbox per repo? How do the GitHub App's installation and repo access apply per repo? How does the Flow Architect (9.x) choose repos? Must it behave the same on Copilot (AC-6)?
- **Links:** roadmap 4.5, 6.3, 6.5, 9.x; seen while testing 5.8 on GildedRoseKata

### Publish a stored workflow as a template

- **Status:** ➡️ Promoted (phase 15.2)
- **Added:** 2026-11-02
- **Problem:** Saving a workflow in the builder makes a new version (5.1), listed under Workflows (5.8), but never a template: templates are Python code (`agentic_engine.templates`) served read-only by `GET /templates`. A tech lead who builds a good flow cannot offer it on the start screen to the rest of the team, although the mission names "publishing templates" as the tech lead's entry point.
- **Idea:** "Publish as template" on a stored version: a name, description, icon, the connections it requires (worked out from the spec, as `workflowRequires` does), and which parameters a user fills in when starting it (for example an agent's instructions or a list of paths). The template is stored per workspace, versioned (draft → published, as 6.6 does for composites), and shown in the gallery beside the built-in ones; updating it publishes a new version.
- **Already covered:** In part. 9.9 promotes highly rated flows to templates automatically (the Architect's learning loop), not on a user's request. 6.6 sets the draft → published pattern for composites. 5.2 opens a template in the builder, the other direction.
- **Open questions:** How are a template's parameters bound to the spec (JSON paths, as `setParam` uses)? Workspace-only, or shared across workspaces? Who may publish? Do built-in templates move to the same storage?
- **Links:** roadmap 5.1, 5.2, 5.8, 6.6, 9.9; mission "Who we serve"

### Later agents can read what earlier writers changed

- **Status:** ➡️ Promoted (phase 13.1)
- **Added:** 2026-11-02
- **Problem:** Each writer commits in its own worktree and branch (`agent/<run>/<node>`); a later agent has only the base checkout. A reviewer agent placed after a test writer and a refactoring writer cannot read either branch, and their replies are not kept unless the spec gives them `writes`. Only the gate's review sheet shows the diffs, to the human. Testing 5.8, a review agent guessed artifact names and reviewed nothing.
- **Idea:** Give agents read access to the run's writer branches: `repo.diff {node}` (the files a writer changed and the diff against its base) and `repo.read_file {path, node}` to read a file as a writer left it. Optionally, a writer's final reply is kept as an artifact by default (`<node>-report.md`). The node's input says which writers ran before it.
- **Already covered:** In part. 6.3 merges worker branches into an integration branch before the final PR, which a later agent could then read. 3.6 and the gate review sheet show the diffs to the approver. 4.3 artifacts carry what a spec declares with `writes`.
- **Open questions:** Is this enough once 6.3 exists, or still needed between writers in sequence? Read-only for every later agent, or only for ones granted it? How large may a diff be before it is cut (the 256 KB artifact cap)?
- **Links:** roadmap 3.6, 4.3, 6.3, 6.4

### Recover runs lost between the queue and the worker

- **Status:** ➡️ Promoted (phase 12.1)
- **Added:** 2026-11-02
- **Problem:** A worker pops a run id from Redis, then claims the run in Postgres. If it crashes between the two, or while parsing the stored spec (seen on 2026-11-02: a worker older than 5.4 could not parse `budget_usd`), the id is gone from the queue and the run has no lease, so `reclaim_expired_run` never sees it. The run stays "Queued" for good, and the console shows "Waiting for the run to start…" with nothing to explain why.
- **Idea:** Treat Postgres as the queue's source of truth: on startup and on a timer, the worker re-enqueues runs that have been `queued` with no lease for longer than a threshold. A run that fails to load (a spec this worker cannot parse) is failed with a clear `failure_reason` rather than crashing the worker. The console could show "Queued for N min" and a hint once that passes the threshold.
- **Already covered:** In part. Leases and `reclaim_expired_run` (1.3) resume only runs a worker stopped mid-way, not runs it never claimed. Rerun (2.6) lets a user start over by hand.
- **Open questions:** Is a version check between API and worker (refusing to claim a spec from a newer schema) needed as well? What threshold avoids re-enqueuing a run another worker is about to claim? Should the API, not the worker, do the sweep?
- **Links:** `agentic_worker.main._next_run`, `agentic_store.lease`; principle 9 (nothing is lost)

### Keep agents' code when a run fails or its worker crashes

- **Status:** ➡️ Promoted (phases 12.2, 12.3)
- **Added:** 2026-11-10
- **Problem:** A run's history is safe in Postgres (events, approvals, run artifacts, checkpoints after each node), but the code its agents write lives only in the run's sandbox volume: the clone and the writers' commits on `agent/<run>/<node>` and the integration branch, until the gated `github.openPR` pushes them. Today that code is lost in several cases:
  - **The run fails, is cancelled, or its approval expires:** the worker deletes the sandbox when the attempt ends (`_attempt` in `agentic_worker.main`); only a run paused at a gate keeps it (`sandboxes.keep`). The user sees what the agents did in the console but cannot get the code back, and a rerun starts from scratch.
  - **The worker crashes mid-run (to confirm with a test):** the checkpointer (1.3) skips the steps that completed, but the sandbox is reopened with `reuse` only after a gate decision (`reuse=decision is not None`), so the resumed run seems to start from a fresh clone, without the commits of the steps it skips. AC-8 holds for the graph, not for the code.
  - **The sandbox is deleted from outside:** a second stack's worker on the same Docker host (`sweep_orphans` keeps only its own database's runs), `test_docker_sandbox.py`, `docker compose down -v` or a volume prune. Seen on 2026-10-22, when a run waiting at a gate lost its sandbox.
- **Idea:** cheapest first, 1 and 2 together as one phase:
  1. **Keep a failed or cancelled run's sandbox** for a time to live (like the 72 h approval expiry), swept after; the console says until when, so it can be inspected or reused by a rerun.
  2. **Save each writer's commits outside the container** when its step completes: a `git bundle` of its branch in Postgres (or object storage in production), restored into the sandbox when an attempt resumes, a run is rerun, or a sandbox is found missing. This closes the crash gap and the sweep gap.
  3. **Push agent branches to GitHub as they are committed** (the most robust): pushing is irreversible (principle 3), so only behind a gate or a workspace opt-in, to a namespace no one reviews (`agentic/wip/<run>/…`), never a PR.
- **Already covered:** In part. 1.3 resumes the graph after the last completed node; 4.3 keeps run artifacts in Postgres and copies them into a fresh sandbox; 2.6 reruns a whole run from scratch. "Rerun from a node, with the code as it was there" below needs the same saved commits.
- **Open questions:** First, a test that kills a worker after a writer's commit and checks what the resumed run's branch holds. How big may a bundle get, and is it kept per node or only the latest per branch? How long are failed sandboxes and bundles kept, and does a budget or a disk limit cap them? Can a rerun start from a failed run's code, or only from the repo's head (a new run, same history)? In production (10.2), where do bundles live?
- **Links:** `agentic_worker.main._attempt`, `agentic_sandbox.docker_backend.sweep_orphans`; roadmap 1.1, 1.3, 1.6, 2.6, 4.3, 6.3, 10.2; AC-8; principle 9 (nothing is lost)

### Commit trailers that link a change back to its run

- **Status:** ➡️ Promoted (phase 14.1)
- **Added:** 2026-11-09
- **Problem:** A commit the platform pushes says nothing about where it came from. Once a PR is merged, the link from the code to the run that wrote it (workflow, version, node, approver, cost) lives only in our database. Someone reading `git log` or `git blame`, or a team that stops running the platform, loses it.
- **Idea:** Every commit the platform makes (a writer's commit, an approver's edits, the integration branch) carries git trailers: `Agentic-Run: <run_id>`, `Agentic-Workflow: <id>@v<version>`, `Agentic-Node: <node>` and, for edits made at a gate, `Agentic-Approved-By: <user>`. `git log --format='%(trailers)'` then gives the run of any line of code, and the console links back from a run id. Entire's Checkpoints CLI does the same with an `Entire-Checkpoint: <id>` trailer.
- **Already covered:** Nothing. Commits are made in the sandbox (`agentic_sandbox.review.commit_files`, the repo write tools) with plain messages; the PR body (1.8) links the run, but only on GitHub and only for the PR as a whole.
- **Open questions:** Which ids are safe to publish in a public repo (a run id is harmless; an approver's name or email may not be)? Should the PR body list the same trailers? Do squash merges on GitHub keep them (they keep the PR body, not each commit's trailers)?
- **Links:** roadmap 1.6, 1.8, 6.3; mission "Traceable delivery"; [Entire Checkpoints](https://docs.entire.io/guides/checkpoints/overview)

### Show why each change was made beside the diff at the gate

- **Status:** ➡️ Promoted (phase 14.2)
- **Added:** 2026-11-09
- **Problem:** The gate's review sheet shows the diff, but not why the agent wrote it. To check a hunk, the approver has to leave the review, find the right agent turn in the console and match it to the file by hand. Review is the slow, risky step once agents write the code.
- **Idea:** Each diff hunk in the review links to the agent turn and tool call (`repo.write_file`, …) that last wrote it, with the agent's short note or reasoning for that turn shown inline or on hover. The events log already has every tool call with its node, turn and arguments; the work blocks (11.8) already render turns. Entire builds its product on this point: agent sessions reviewed as artifacts beside the code.
- **Already covered:** In part. 3.6 and the editable gate artifacts show and edit the diff; 11.8 shows agent turns as work blocks in the console. Nothing joins the two.
- **Open questions:** How is a hunk matched to a write when several turns touch the same file (last write wins, or every turn listed)? How much reasoning is shown, given that not every provider streams it? Is the reasoning untrusted text to render as such (principle 5 and rule 11)? Same view on Copilot (AC-6)?
- **Links:** roadmap 1.7, 3.6, 11.5, 11.8; principle 6 (transparency)

### Rerun from a node, with the code as it was there

- **Status:** ➡️ Promoted (phase 12.4)
- **Added:** 2026-11-09
- **Problem:** Rerun (2.6) starts a run over from the first node. When a long flow (an SDD run, an audit with fixes) goes wrong at its last step, the user pays again for every step before it. The checkpointer (1.3) resumes a run that stopped, but nothing lets a user go back to a node and try it again, for example with changed instructions.
- **Idea:** After each node, the run keeps a snapshot of the state and of the code (the writer branches' commits are enough while writes go through git). The console offers "Rerun from here" on a node: a new run starts from that node's checkpoint, with the code restored, optionally with edited node parameters, and links to the run it came from. Entire's `rewind` restores code to an earlier checkpoint of an agent session in the same way.
- **Already covered:** In part. 1.3 durable execution keeps a checkpoint after each node; 2.6 reruns a whole run; 5.7 runs any version of a workflow. 7.6 (a review comment resumes the run) and 9.8 (runtime adaptation at checkpoints) need the same mechanism.
- **Open questions:** A new run or a new attempt within the same run (history and cost reporting differ)? Which edits are allowed from a checkpoint: parameters only, or the graph after the node (a new workflow version)? How long are checkpoints and branches kept? What about effects outside the sandbox that already happened (a pushed branch, a Jira comment)?
- **Links:** roadmap 1.3, 2.6, 5.7, 7.6, 9.8; principle 9 (nothing is lost)

### Keep a run's record in the repo itself (opt-in)

- **Status:** ➡️ Promoted (phase 14.5)
- **Added:** 2026-11-09
- **Problem:** The audit trail of a run (workflow version, prompts, tool calls, cost, approvals) lives only in the platform's Postgres. A team that moves deployments, loses its database or stops using the platform loses the story behind its code, and auditors must be given access to the platform to see it.
- **Idea:** As an opt-in per workspace or workflow, the platform writes a short run record (JSON plus a readable summary) to an orphan branch of the repo, such as `agentic/runs/v1`, which shares no history with the code and holds only metadata. Commit trailers (idea above) point into it. Entire stores its checkpoints the same way, on an `entire/checkpoints/v1` orphan branch, so code branches stay clean.
- **Already covered:** Nothing. The events log (0.5) and audit log view (3.7) keep everything, but only in the platform.
- **Open questions:** Writing to the repo is a write action: does it go through a gate, or is approving the PR enough? What is left out (secrets never; prompts and repo content may be sensitive in a public repo)? Size limits for long runs? Does it conflict with branch protection rules?
- **Links:** roadmap 0.5, 3.7, 10.5; principles 3 and 6; mission v1 decision "open source, self-hosted first"; the commit trailers idea above

### Measure how much of a change people edited before approving

- **Status:** ➡️ Promoted (phase 14.3)
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

### Template library: overview and what it needs

- **Status:** ➡️ Promoted (Milestone 16)
- **Added:** 2026-11-09
- **Problem:** The template library entries below list about 150 templates. Built one by one with no order, they would sprawl, and many depend on capabilities the platform does not have yet.
- **Idea:** Build them in waves, by what they need:
  1. **Repo only, with today's primitives (🟢):** most of the list. Start with Fix an issue, Dependency upgrade, Security audit, Add a CI pipeline and Generate IaC for an existing app.
  2. **Sandbox tooling:** IaC tools (`terraform`, `tflint`, `kubeconform`), a headless browser, a throwaway database, Trivy. Each is an image size and egress question like .NET in 4.8.
  3. **Integrations (🟡):** CI logs and history, the GitHub security API, Jira (milestone 7), read-only cloud access (entry below), read-only database access, vaults.
  4. **Platform features:** scheduled triggers (see "Repo healer"), several repos per run, Markdown upload, templates stored as published workflows.
  Each template is a flow of existing primitives, so the work for most is the prompts, tool grants, checks and a validation run, not engine code.
- **Already covered:** Three templates (Generate docs, Audit, New repo); 7.5 SDD planned.
- **Open questions:** A milestone "Template library" with one phase per wave? A quality bar each template must pass before it ships (a real repo, a cost ceiling, a success rate)? Do templates stay Python code or become stored workflows?
- **Links:** ideas "Publish a stored workflow as a template", "Repo healer", "Workflows that work on several repos", "Upload a Markdown file", "Read-only cloud access per workspace"

### Template library: software engineering

- **Status:** ➡️ Promoted in part (phases 16.1, 16.2); the rest of the catalogue stays here
- **Added:** 2026-11-09
- **Problem:** The start screen offers three templates (Generate docs, Audit, New repo), plus SDD planned in 7.5. The everyday tasks a developer would hand to agents have no ready-made flow, so every team draws them from scratch in the builder.
- **Idea:** Built-in templates, each a flow made of existing primitives. 🟢 = needs only the repo (sandbox and a PR behind a gate); 🟡 = needs a new integration.
  - 🟢 **Fix an issue:** read an issue, reproduce it, fix it, add a test, open a PR (agent → test loop → gate → PR). A first step toward 7.5.
  - 🟢 **Write missing tests:** find untested code and write tests until coverage reaches a target (orchestrator per module → loop on the test run).
  - 🟢 **Dependency upgrade:** move to a new library or framework version (.NET 8 → 10, React 18 → 19) and fix what breaks (plan → gate → implement → build and test loop → PR).
  - 🟢 **Refactor or migration across the codebase:** rename an API, replace a library, move to async (orchestrator, one worker per folder).
  - 🟢 **PR review:** review a PR for bugs, style and spec compliance and post comments (parallel reviewers → merged findings).
  - 🟢 **Dead code and lint cleanup:** remove unused code and fix analyzer warnings (`scan.lint`, 4.8 → agent → PR).
  - 🟢 **API docs and OpenAPI sync:** keep an OpenAPI spec or SDK in step with the code (agent → diff at a gate → PR).
  - 🟢 **Changelog and release notes:** write release notes from the PRs merged since the last tag (agent → gate).
  - 🟡 **Fix a failing CI build:** read the failing job's log, fix the cause, push to the same branch. Needs CI log access.
  - 🟢 **Implement a feature from a spec file:** a Markdown spec in the repo or uploaded → plan → gate → orchestrator → PR. 7.5 without Jira; see "Upload a Markdown file".
  - 🟢 **Reproduce a bug:** write a failing test that reproduces an issue, without fixing it, so a person or a later run can fix it.
  - 🟢 **Language or runtime migration:** JavaScript → TypeScript, Python 2 → 3, .NET Framework → .NET, Java 8 → 21 (orchestrator per folder → build loop → PR).
  - 🟢 **Framework migration:** AngularJS → React, class components → hooks, Next.js Pages Router → App Router, Express → Fastify.
  - 🟢 **Add types:** TypeScript `strict`, Python type hints, C# nullable reference types, until the type checker passes (loop on the checker).
  - 🟢 **Test framework port:** Jest → Vitest, NUnit → xUnit, unittest → pytest, with the same tests passing.
  - 🟢 **Improve weak tests:** run mutation testing (Stryker, mutmut) and strengthen the tests that let mutants survive.
  - 🟢 **Error handling review:** swallowed exceptions, missing retries, unclear error messages, unchecked results (audit → fix PR).
  - 🟢 **Logging cleanup:** consistent levels and structure, no personal data or secrets in logs.
  - 🟢 **Feature flag cleanup:** remove flags that are fully rolled out, and the dead branch of each.
  - 🟢 **TODO and FIXME triage:** fix the small ones, list the rest as proposed issues.
  - 🟢 **Remove duplication:** find copy-pasted code and extract it into shared functions.
  - 🟢 **Scaffold an endpoint or CRUD feature:** following the repo's own conventions (route, handler, validation, tests, docs).
  - 🟢 **Generate a client SDK:** from an OpenAPI spec, with tests and a README.
  - 🟢 **Resolve merge conflicts:** rebase a stale branch on main and resolve the conflicts, with the tests passing (gate before push).
  - 🟢 **Split a large PR:** turn one large change into a stack of smaller, reviewable PRs.
  - 🟡 **Backport a fix:** cherry-pick a merged fix onto release branches and adapt it where it does not apply. Needs release-branch conventions.
  - 🟡 **Contract tests between services:** consumer and provider tests (Pact) across two repos. Needs "Workflows that work on several repos".
- **Already covered:** In part. 4.6 Audit and 6.7 (audit findings to fix PRs) cover cleanup; 7.5 SDD covers spec-to-PR; 7.6 covers PR comments. The "Repo healer" idea above overlaps with dependency upgrades.
- **Open questions:** Which come first? Suggested: Fix an issue, Dependency upgrade. Is a template Python code (today) or a stored, published workflow (the "Publish a stored workflow as a template" idea above)? Does PR review post comments without a gate (a write to GitHub)?
- **Links:** roadmap 4.6, 4.8, 6.1, 6.7, 7.5, 7.6; ideas "Repo healer", "Publish a stored workflow as a template"

### Template library: DevOps

- **Status:** ➡️ Promoted in part (phase 16.5); the rest of the catalogue stays here
- **Added:** 2026-11-09
- **Problem:** Build, packaging and delivery setup is repetitive and well understood, yet no template covers it.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Add a CI pipeline:** write a GitHub Actions workflow (build, test, lint) for the repo's stack (profile → agent → PR).
  - 🟢 **Containerise an app:** write a Dockerfile, `.dockerignore` and compose file, and check the image builds (agent → build loop → PR).
  - 🟢 **Pipeline hardening:** pin actions to SHAs, add caching, least-privilege `permissions:` and concurrency groups (audit → fix → PR).
  - 🟢 **Observability setup:** add structured logging, health checks and OpenTelemetry to a service (agent → PR).
  - 🟡 **Flaky test hunter:** find tests that fail now and then across CI runs, then fix or quarantine them. Needs CI history.
  - 🟡 **Incident postmortem draft:** a timeline and postmortem from logs, alerts and commits. Needs log and alert sources.
  - 🟢 **Release automation:** release-please or semantic-release, version bumps, tags and a release workflow.
  - 🟢 **Dependency bot setup:** Dependabot or Renovate config with sensible grouping and schedules.
  - 🟢 **Developer tooling:** formatter, pre-commit hooks and `.editorconfig` for the repo's stack.
  - 🟢 **Dev container:** a `devcontainer.json` (Codespaces) that builds and runs the tests.
  - 🟢 **"Run it locally" check:** follow the README in the sandbox, step by step, and fix the steps that fail.
  - 🟢 **CI speed-up:** caching, parallel jobs, test splitting, skipping unchanged paths (static review → PR).
  - 🟢 **CI migration:** Azure Pipelines, Jenkins or GitLab CI → GitHub Actions, with the same jobs.
  - 🟢 **Deployment pipeline:** environments, required approvals and a blue-green or canary rollout in the workflow.
  - 🟢 **Monitoring as code:** alert rules, SLOs and dashboards (Prometheus, Grafana, Azure Monitor) for a service.
  - 🟢 **Runbooks:** a runbook per service from its code, config and alerts (how to restart, scale, roll back).
  - 🟢 **CODEOWNERS:** a CODEOWNERS file from the commit history and folder structure.
  - 🟡 **Deployment failure triage:** read the failed deploy's logs, name the cause, propose a fix or a rollback.
  - 🟡 **Alert triage:** link a firing alert to recent commits and deploys, and propose the likely cause.
  - 🟡 **Branch protection setup:** required checks, reviews and merge rules. Needs GitHub admin rights (a write behind a gate).
- **Already covered:** Nothing.
- **Open questions:** Can the sandbox build container images (Docker in the sandbox is a new trust question), or is a Dockerfile lint enough? Which CI systems besides GitHub Actions?
- **Links:** roadmap 9.1 (RepoProfile); mission non-goals (other hosts later as adapters)

### Template library: cloud

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Cloud reviews (cost, architecture, migration) are slow expert work, and teams already keep much of what they need in their IaC.
- **Idea:** 🟢 = repo only (reads the IaC); 🟡 = needs live cloud access (see "Read-only cloud access per workspace" below).
  - 🟢 **Cloud cost review (IaC):** flag oversized SKUs, missing autoscale and always-on dev resources in Terraform or Bicep (parallel per module → report).
  - 🟢 **Well-Architected review:** check the IaC against the Azure or AWS pillars: reliability, security, cost, operations, performance (parallel per pillar → report).
  - 🟢 **Cloud migration plan:** map an app's dependencies and propose target services and a plan (profile → agent → report → gate).
  - 🟡 **Live cost and drift report:** compare deployed resources with the IaC and list cost anomalies.
  - 🟡 **Orphaned resource cleanup:** find unused disks, IPs and old snapshots and propose deleting them; every deletion behind a gate.
  - 🟢 **Tagging policy:** add the required tags (owner, cost centre, environment) to every resource in the IaC.
  - 🟢 **Keys to managed identity:** replace connection strings and access keys with managed identities or IAM roles, in code and IaC.
  - 🟢 **High availability and DR review:** zones, backups, failover and recovery targets, with a disaster recovery plan as a document.
  - 🟢 **Policy as code:** Azure Policy, AWS SCPs or OPA rules from the team's written standards.
  - 🟢 **Landing zone scaffold:** subscriptions or accounts, networking, identity and guardrails as IaC.
  - 🟢 **Serverless or PaaS proposal:** which parts of an app could move to functions or managed services, with the trade-offs.
  - 🟢 **Portability review:** where the app is tied to one cloud and what moving would cost.
  - 🟡 **Rightsizing from metrics:** resize from real CPU and memory use, as a PR to the IaC.
  - 🟡 **Reservations and savings plans:** recommend commitments from steady usage.
  - 🟡 **Quota check before a deployment:** check the target subscription or account has room for what the IaC adds.
- **Already covered:** In part. The Audit template (4.6) has the parallel-review → report shape.
- **Open questions:** Azure first, AWS first, or both? Are the reviews checklists the agents follow (a skill, see "Skills usable in flows and agents") or free judgement?
- **Links:** roadmap 4.5, 4.6; ideas "Skills usable in flows and agents"

### Template library: infrastructure

- **Status:** ➡️ Promoted in part (phases 16.6, 16.7); the rest of the catalogue stays here
- **Added:** 2026-11-09
- **Problem:** Writing and maintaining IaC and deployment manifests is a large share of platform teams' work, and none of it has a template.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Generate IaC for an existing app:** Terraform or Bicep for what the app needs (database, storage, app service) (profile → agent → validate loop → PR).
  - 🟢 **Terraform module upgrade:** upgrade provider or module versions and fix deprecations (agent → `terraform validate` loop → PR).
  - 🟢 **Kubernetes manifest review:** resource limits, probes, replicas, PDBs, `securityContext` (audit → fix PR).
  - 🟢 **Helm chart or Kustomize scaffold:** deployment manifests for a service (agent → lint loop → PR).
  - 🟢 **Environment parity check:** diff dev, staging and prod config in the repo and flag gaps (report).
  - 🟡 **Terraform plan review:** run `terraform plan`, explain the changes and flag destructive ones. Needs the state backend; apply always behind a gate, if ever.
  - 🟢 **IaC conversion:** ARM → Bicep, Bicep ↔ Terraform, CloudFormation → CDK, with the same resources.
  - 🟢 **Extract modules:** turn duplicated IaC into reusable modules with inputs, outputs and a README.
  - 🟢 **IaC module docs:** `terraform-docs` READMEs and examples for every module.
  - 🟢 **Network diagram from IaC:** a Mermaid or C4 diagram of networks, subnets, peering and endpoints.
  - 🟢 **Kubernetes upgrade readiness:** find APIs removed in the next Kubernetes version and update the manifests.
  - 🟢 **Slim container images:** multi-stage builds, distroless or minimal bases, non-root users, smaller layers.
  - 🟢 **GitOps setup:** Argo CD or Flux manifests for the repo's services.
  - 🟢 **Configuration management fix:** lint and fix Ansible playbooks, Chef or Puppet code.
  - 🟡 **Import hand-made resources into IaC:** write IaC and import blocks for resources created in the portal. Needs cloud access.
  - 🟡 **Drift remediation:** update the IaC to match intended live changes, or propose reverting the unintended ones.
- **Already covered:** Nothing. 4.4 deterministic tool nodes are where `terraform validate`, `tflint` or `kubeconform` would run.
- **Open questions:** Which IaC tools go in the sandbox image (size, as with the .NET SDK in 4.8)? Do provider plugins need an egress proxy like NuGet's? Is `apply` a non-goal?
- **Links:** roadmap 4.4, 4.8 (egress proxy pattern)

### Template library: security

- **Status:** ➡️ Promoted in part (phases 16.3, 16.4); the rest of the catalogue stays here
- **Added:** 2026-11-09
- **Problem:** The Audit template reports findings once, but common security work (secrets, vulnerable dependencies, IaC misconfigurations, threat models) has no flow that finishes the job.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Security audit (OWASP):** injection, authentication, secrets, unsafe deserialisation; one fact per finding (parallel per category → report). Close to the Audit template.
  - 🟢 **Secret scan and remediation:** move committed secrets to config or a vault reference and list the keys to rotate (scan → gate → PR).
  - 🟢 **Vulnerable dependency fix:** read `npm audit`, `pip-audit` or `dotnet list package --vulnerable` and upgrade with tests (loop → PR).
  - 🟢 **IaC security scan:** public buckets, open security groups, missing encryption, wildcard IAM (scan → fix PR).
  - 🟢 **Threat model:** a STRIDE threat model from the architecture and code (profile → agent → document → gate).
  - 🟢 **SBOM and licence check:** an SBOM, with licences that conflict with the project's flagged (report).
  - 🟡 **Triage scanner alerts:** read Dependabot or CodeQL alerts, drop false positives, fix the real ones. Needs the GitHub security API.
  - 🟢 **Authorisation review:** every endpoint and handler checks who may call it; missing or inconsistent checks listed and fixed.
  - 🟢 **Input validation hardening:** validate and bound every external input (requests, files, messages).
  - 🟢 **Security headers and CORS:** CSP, HSTS, cookie flags and CORS rules for a web app.
  - 🟢 **CI workflow security:** `pull_request_target` misuse, script injection from untrusted input, over-broad tokens, unpinned actions.
  - 🟢 **Cryptography review:** weak hashes, hard-coded keys, insecure randomness, home-made crypto.
  - 🟢 **Security tests:** tests for authentication bypass, injection and access to other users' data.
  - 🟢 **Supply chain check:** lockfiles present and used, versions pinned, typosquatted or abandoned packages flagged.
  - 🟢 **Is the CVE reachable?** For a vulnerable dependency, find whether the code calls the vulnerable function, to rank the fix.
  - 🟢 **Container image scan and fix:** scan the Dockerfile and image (Trivy) and upgrade the base or packages.
  - 🟢 **Security policy:** `SECURITY.md` and a disclosure process.
  - 🟢 **Pen test remediation:** read a pen test report (an uploaded file) and turn each finding into a fix PR or a proposed issue.
  - 🟢 **LLM app security review:** prompt injection, tool permissions, untrusted content passed to a model, output used as code.
  - 🟡 **Leaked secret response:** rotate a leaked key in the vault and update its users. Needs vault access; every rotation behind a gate.
- **Already covered:** In part. 4.4 has a secret scanner and dependency scanner as tool nodes; 4.6 Audit; 6.7 fix PRs from findings; the "Repo healer" idea above.
- **Open questions:** Does a secret found in history (not only the current tree) need a history rewrite, which is out of scope? Are security findings hidden from other workspace members?
- **Links:** roadmap 4.4, 4.6, 6.7; ideas "Repo healer"; `docs/` security model

### Template library: frontend and UX

- **Status:** ➡️ Promoted in part (phases 16.8, 16.9); the rest of the catalogue stays here
- **Added:** 2026-11-09
- **Problem:** Frontend work has many repetitive, checkable tasks (accessibility, translations, performance, tests) that no template covers.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Accessibility audit and fix:** WCAG 2.2 AA with axe in a headless browser, then fixes (loop until axe passes → PR).
  - 🟢 **Internationalisation:** extract hard-coded strings into message files and add a locale.
  - 🟢 **Design system migration:** replace hand-made components and raw colours with the design system's components and tokens.
  - 🟢 **Bundle and load performance:** bundle size, code splitting, lazy loading, image formats, against a budget.
  - 🟢 **End-to-end tests for key journeys:** Playwright tests for sign-in, checkout or the app's main flows.
  - 🟢 **Component stories:** Storybook stories for every component, with their states.
  - 🟢 **Responsive layout fixes:** screenshots at 375, 768 and 1440 px, then fixes for overflow and broken layouts.
  - 🟢 **SEO and metadata review:** titles, descriptions, structured data, sitemap, robots.
  - 🟢 **Mobile SDK bump:** raise the Android target SDK or the iOS deployment target and fix what breaks.
  - 🟡 **Visual regression triage:** sort screenshot diffs into intended changes and bugs. Needs baseline storage.
- **Already covered:** Nothing. This repo's own `web/` checks (axe, layout screenshots) show the pattern.
- **Open questions:** Does the sandbox image ship a headless browser (size, as with .NET in 4.8)? How are screenshots shown at the gate?
- **Links:** roadmap 4.8; rules in `CLAUDE.md` (the same checks this repo runs)

### Template library: data and databases

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Database and data pipeline changes are risky and slow to review, and no template helps with them.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Schema migration with rollback:** a migration for a model change, its rollback, and a test that applies and reverts it.
  - 🟢 **Query review:** N+1 queries, missing indexes and unbounded queries found in ORM code, fixed in a PR.
  - 🟢 **Seed and fixture data:** realistic, non-personal test data for local development and tests.
  - 🟢 **ORM or driver upgrade:** Entity Framework, SQLAlchemy, Prisma, with the migrations and tests passing.
  - 🟢 **dbt models:** documentation and tests (unique, not null, relationships) for every model.
  - 🟢 **Data pipeline review:** Airflow DAGs or Spark jobs for idempotency, retries, partitioning and cost.
  - 🟢 **Schema documentation:** a data dictionary and an ER diagram from the migrations or models.
  - 🟡 **Slow query analysis:** read the database's query stats and propose indexes or rewrites. Needs read-only database access.
- **Already covered:** Nothing.
- **Open questions:** Can the sandbox run a throwaway database (Postgres, SQL Server) to test a migration? Is any access to a real database in scope, and only read-only?
- **Links:** roadmap 4.4, 4.8 (job containers)

### Template library: AI and ML engineering

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Teams building LLM features and ML models have their own repeatable chores (evals, reproducibility, provider upgrades), and they are likely early users of an agent platform.
- **Idea:** 🟢 = repo only.
  - 🟢 **Eval suite for an LLM feature:** write eval cases and a runner for a prompt or agent in the repo.
  - 🟢 **Model or provider SDK upgrade:** move to a new model version or SDK, update prompts and parameters, run the evals.
  - 🟢 **Notebook to pipeline:** turn a Jupyter notebook into a tested, parameterised module.
  - 🟢 **ML reproducibility:** pinned versions, seeds, data versioning and a documented training command.
  - 🟢 **Model and dataset cards:** documentation of intended use, data, metrics and limits.
  - 🟢 **Prompt review:** prompts kept in code checked for injection risk, unclear instructions and duplication.
- **Already covered:** Nothing.
- **Open questions:** Do evals call a model from the sandbox (cost, keys; the sandbox has no model keys today)? GPU work is out of scope?
- **Links:** the "LLM app security review" entry under security

### Template library: documentation and knowledge

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Generate docs (the only docs template) writes reference docs. Teams also need onboarding guides, decision records and docs that stay true over time.
- **Idea:** 🟢 = repo only.
  - 🟢 **Onboarding guide:** a codebase tour for a new developer: where things live, how a request flows, how to run and test.
  - 🟢 **Architecture diagrams:** C4 or Mermaid diagrams generated from the code and config.
  - 🟢 **Decision records from history:** draft ADRs for past decisions found in commits, PRs and code.
  - 🟢 **Docs drift check:** compare the docs with the code and fix what is out of date (scheduled, with the "Repo healer" idea).
  - 🟢 **Docstrings and comments:** public APIs documented in the language's own format.
  - 🟢 **Migration guide:** a guide for users of a library through a breaking release, from the diff between two tags.
  - 🟢 **Translate the docs:** keep docs in a second language in step with the first.
  - 🟢 **FAQ from issues:** answers to the questions asked most in issues and discussions.
- **Already covered:** In part. Generate docs (1.x template) and the Architect's RepoProfile (9.1).
- **Open questions:** Are these new templates, or options of Generate docs?
- **Links:** roadmap 9.1; idea "Repo healer"

### Template library: planning and project management

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Before and around code there is planning work (triage, splitting, estimating, reporting) that agents can draft for people to approve.
- **Idea:** 🟢 = repo only; 🟡 = needs Jira (milestone 7) or GitHub issues.
  - 🟡 **Issue triage:** label, deduplicate, ask for missing details and link duplicates.
  - 🟡 **Split an epic:** stories with acceptance criteria and a suggested order, written back to Jira behind a gate.
  - 🟡 **Bug report enrichment:** add reproduction steps, the suspect commit (`git bisect` in the sandbox) and the files involved.
  - 🟡 **Sprint or release summary:** what shipped, from merged PRs and closed issues, for a non-technical reader.
  - 🟢 **Impact analysis:** what a proposed change touches (code, tests, docs, consumers) and how risky it is, as a report.
  - 🟢 **Tech debt register:** a ranked list of debt found in the code, with effort and impact.
- **Already covered:** In part. Milestone 7 (Jira read, comment, transition; webhook triggers).
- **Open questions:** Creating issues is a write: gate each, or approve the batch? GitHub issues as well as Jira?
- **Links:** roadmap 7.1–7.5; idea "Repo healer" (issue dedupe)

### Template library: compliance and governance

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Audits and policies ask for the same evidence and the same repo hygiene again and again.
- **Idea:** 🟢 = repo only.
  - 🟢 **Repo hygiene standard:** README, LICENSE, CODEOWNERS, SECURITY.md, CONTRIBUTING and issue and PR templates, filled in for the repo.
  - 🟢 **Open-source readiness:** licences, secrets, internal names and URLs, and the docs a public repo needs (what this repo did in #155).
  - 🟢 **Licence headers:** add or fix file headers to the project's licence.
  - 🟢 **Personal data map:** where personal data is collected, stored, logged and sent, for GDPR records.
  - 🟢 **Control evidence:** map SOC 2 or ISO 27001 controls to evidence in the repo (reviews required, scans in CI, access rules) and list the gaps.
  - 🟢 **Accessibility conformance report:** a report against WCAG from the audit above.
- **Already covered:** In part. The audit log (3.7) is evidence for the platform's own runs.
- **Open questions:** Which frameworks are worth templates? Is the output a report only, or PRs that close the gaps?
- **Links:** roadmap 3.7; PR #155

### Template library: performance and reliability

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Problem:** Performance and resilience work needs measurement and careful change, and is often skipped until an incident.
- **Idea:** 🟢 = repo only; 🟡 = needs a new integration.
  - 🟢 **Load test scripts:** k6 or Locust scripts for the main endpoints, with thresholds.
  - 🟢 **Benchmark and optimise:** run benchmarks in the sandbox, optimise a hot path, and show before and after (loop until better or out of budget).
  - 🟢 **Resilience review:** timeouts, retries with backoff, circuit breakers, idempotency, graceful shutdown.
  - 🟢 **Caching review:** where caching would help and what invalidates it.
  - 🟢 **Memory and resource leaks:** unclosed connections, growing caches, missing disposal.
  - 🟡 **Chaos experiments:** experiment definitions (Chaos Mesh, Azure Chaos Studio) for a service's failure modes. Running them needs cloud access.
- **Already covered:** Nothing.
- **Open questions:** Are sandbox benchmarks stable enough to compare (shared CPU)? How long may a benchmark job run?
- **Links:** roadmap 4.8 (job containers and their limits)

### Read-only cloud access per workspace

- **Status:** ➡️ Promoted (phases 19.3, 19.4)
- **Added:** 2026-11-09
- **Problem:** The 🟡 cloud and infrastructure templates above need to read what is deployed (resources, costs, Terraform state), but a run can reach only the repo, GitHub and Jira.
- **Idea:** A workspace connects a cloud account (Azure first: a service principal or workload identity; then AWS) with read-only rights, stored encrypted like the other connections. Agents get read tools (list resources, cost by resource, read state) through an MCP server and never see the credentials. Any change (delete, resize, apply) is a write behind a gate, and may stay out of v1.
- **Already covered:** Nothing. 7.1 sets the per-workspace OAuth and encrypted-credential pattern for Atlassian.
- **Open questions:** A milestone of its own? Is any cloud write in scope, or reports and PRs only? How are costs from the cloud's own APIs kept apart from the run's model cost?
- **Links:** roadmap 7.1, 7.2; mission non-goals; the cloud and infrastructure template ideas above

### Vision: an AI software factory, everything in one place

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Parked:** with the AI software factory vision (2026-11-10). It needs a mission change before it can be a phase: it changes the mission's purpose and its scope beyond a reviewable PR. Its parts that fit the current mission are promoted on their own (Milestones 12–20).
- **Problem:** The mission describes a workflow platform: flows of agents on repos, with gates. The industry in 2026 talks about a **software factory**: one place where work comes in (a ticket, an alert, a schedule), agents specify, build, verify, review, ship and watch it, and people set the intent and approve. Today the platform covers the middle of that line (repo → PR); intake, verification, release and operations live in other tools.
- **Idea:** Make the product an AI software factory: **anything a software team does can be started, run, verified, governed and traced in one place.** The ideas below are its parts, each taken from what Google, Anthropic, OpenAI, GitHub, AWS and others published in 2025–2026:
  - **Intake:** triage and a tracker as the control plane (Symphony, Kiro).
  - **Specify:** a PRD, a spec and a prototype together; spec quality is the bottleneck (Google, Kiro).
  - **Build:** long-running agents with progress artifacts (Anthropic); any vendor's agent as a node (GitHub Agent HQ).
  - **Verify:** evidence before the gate; the grader protected from the agent; evals of the factory itself (Google, Anthropic, OpenAI).
  - **Review:** independent reviewers through several lenses; a review queue with limits (Google SRE, OpenAI).
  - **Ship:** a deploy shepherd with progressive rollout and error budgets (OpenAI, Google SRE).
  - **Operate:** production feedback loops into new work (OpenAI's Perf Factory and Sevbot).
  - **Govern:** earned autonomy per change class, circuit breakers, dry runs, a control plane (Google SRE, GitHub).
  - **Understand:** provenance, "ask a run why", factory metrics (Entire, Osmani's "comprehension debt").
  The line through all of it is Google's "an agent is a model plus a harness": the platform *is* the harness, and the harness is where the product wins, whatever model sits inside.
- **Already covered:** The core: primitives, sandbox, gates, events, budgets, audit (milestones 0–6); SDD (7.5) planned; the template library and Entire ideas above.
- **Open questions:** Does this change the mission's one-line purpose and its non-goals (deploying to production, operating services)? It is a mission change, so it goes into `mission.md` before any phase. Which parts stay integrations (CI, deploy, monitoring) and which become our own?
- **Links:** `mission.md`; every idea below; [Google: The New SDLC With Vibe Coding (via Osmani)](https://addyosmani.com/blog/new-sdlc-vibe-coding/); [Inside OpenAI's agentic software factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory); [GitHub Agent HQ](https://github.blog/news-insights/company-news/welcome-home-agents/); [awesome-software-factories](https://github.com/varun1505/awesome-software-factories)

### Ticket to production: the whole lifecycle as one flow

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Parked:** with the AI software factory vision (2026-11-10). It needs a mission change before it can be a phase: its QA (a preview environment), release and watch stages reach deployed environments, beyond v1's reviewable PR. Its earlier stages are promoted on their own (7.7, 7.8, 18.3, Milestone 13, 18.6).
- **Problem:** 7.5 SDD runs ticket → spec → plan → code → review → PR → Jira update. Nothing writes a PRD before the spec, requires tests, follows the PR through CI and QA, or takes the change to production and watches it. The end-to-end story a buyer asks for ("from a ticket to prod") cannot be shown.
- **Idea:** A milestone after 7 that wraps 7.5 into the full chain, each stage a node with its own gate:
  1. **Intake and triage:** the ticket is labelled ready-to-spec, ready-to-implement, needs-info or wait (see "Triage agent").
  2. **PRD:** an agent writes the product requirements (problem, users, success measures, scope) → gate.
  3. **Spec and prototype:** the technical spec and a throwaway prototype on a branch (see "Spec and prototype together") → gate.
  4. **Build and verify:** 7.5's orchestrator, with evidence before the gate (see "Verification gates").
  5. **PR shepherd:** the agent follows the PR until CI is green and answers review comments (see "PR shepherd").
  6. **QA:** end-to-end tests against a preview environment; QA findings go back to the build step.
  7. **Release:** after a person merges, deploy to staging then production behind a gate, rolled out gradually (see "Deploy shepherd").
  8. **Watch and close:** health checks after release, fix-forward or rollback proposed, the ticket closed with links to the PR, the run and the release.
- **Already covered:** In part: 7.1–7.6 for stages 1, 3, 4 and 5; the template library for the pieces (Fix a failing CI build, deployment pipeline).
- **Open questions:** Which CI and deploy systems first (GitHub Actions and Azure, given the team)? Is production deploy in scope at all, or does the factory stop at "ready to deploy" with a human pressing the button? Can 6.3 and milestone 7 move ahead of 6.4–6.8 to show the core chain sooner?
- **Links:** roadmap 6.3, 7.1–7.6; mission non-goals ("merging to protected branches without human approval"); [FDEInterviews: issue-to-production factory](https://fdeinterviews.com/blog/agentic-software-factory)

### Earned autonomy per change class

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Parked:** with the AI software factory vision (2026-11-10). It needs a mission change before it can be a phase: auto-approving writes goes against principle 3 (every push and PR goes through a gate) and the v1 decision that autonomous mode never skips a write gate. 14.3's edit share and 20.5's metrics give it the signal it would need.
- **Problem:** Today every write waits at a gate, whatever the risk. A docs typo and a payments change get the same human attention, so approvers either drown or rubber-stamp. Every company running agents at scale has hit this.
- **Idea:** Autonomy is a level, earned per **change class** and lost on failure:
  - **Change classes** are declared per workspace from paths, labels and the workflow: for example `docs`, `tests-only`, `deps-patch`, `app-code`, `infra`, `security-sensitive`. A run's change is classified by rules first (paths touched, files added), then by an agent for what the rules cannot decide.
  - **Levels** follow Google SRE's L0–L4: L0 the agent only suggests; L1 every write gated (today); L2 gated with an agent pre-review; L3 auto-approved when all verification evidence passes, a person reviews a sample; L4 auto-approved and auto-merged to non-protected branches. Protected branches and production never go past "gated" (mission non-goal).
  - **Promotion ledger:** a class moves up after N changes approved with no edits (see "Measure how much of a change people edited") and no revert within a window; it drops back a level automatically on a revert, a failed deploy or a security finding, and a person can drop it at any time. Every promotion and demotion is an audit event.
  - The console shows a run's class and level, and why the gate opened or waited.
- **Already covered:** In part. 9.7 Manual and Autonomous modes (write gates always enforced); 3.7 audit; the edit-share idea above gives the signal.
- **Open questions:** Who may raise a class's ceiling (admin only)? How long is the window before an approved change counts as good? Is a sample review (weekly audit of random approvals) mandatory at L3 and up? Does the level belong to the workflow, the class, or both?
- **Links:** roadmap 3.7, 9.7; mission non-goals; [Google SRE: Progressive Authorization, L0–L4](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); OpenAI's risk-classified changes and opt-in auto-approve ([Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/openai-software-factory)); FDEInterviews (autonomy per change class with promotion and demotion)

### Verification gates: evidence before a person looks

- **Status:** ➡️ Promoted in part (phases 13.2–13.4; the mutation score and pass^k stay here)
- **Added:** 2026-11-09
- **Problem:** A gate shows a diff and asks a person to judge it. Whether the tests pass, whether new code is tested, and whether the analyzers are clean is left to the approver to find out, or to CI after the PR is open. Google's paper puts it plainly: "verification is the line" between vibe coding and engineering.
- **Idea:** A writer's work reaches a gate only with an **evidence pack**, produced by deterministic tool nodes, not by the agent's own claim:
  - build passes; the full test suite passes; new and changed lines are covered, and coverage did not drop;
  - **fail-to-pass per requirement:** for each acceptance criterion in the spec, a test that failed before the change and passes after;
  - analyzers and scanners (4.4, 4.8) show no new findings;
  - optionally a mutation score on changed lines (Meta's mutation-testing work, Stryker, mutmut);
  - **pass^k:** for flaky-prone work, the tests pass k times in a row.
  The gate shows the pack as a stat strip with each check's status beside the diff; a failing check sends the work back to the writer loop instead of to a person. The thresholds are part of the workflow spec.
- **Already covered:** In part. 4.4 deterministic tool nodes; 4.2 typed ports; `loop` exists for retry. No node produces coverage or fail-to-pass evidence, and the gate does not show checks.
- **Open questions:** How is a requirement linked to its tests (ids in the spec and test names)? Coverage tools per language in the sandbox image? What does the gate do when the repo has no tests at all (a "write tests first" step)?
- **Links:** roadmap 4.2, 4.4, 4.8, 7.5; [Google SRE](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); Anthropic's test-first loop ([Claude Code best practices](https://www.anthropic.com/research/claude-code-best-practices)); FDEInterviews (fail-to-pass, mutation score, pass^k)

### Protect the grader: agents cannot change what judges them

- **Status:** ➡️ Promoted (phase 13.5; sealed tests in 17.3)
- **Added:** 2026-11-09
- **Problem:** An agent told to make the tests pass can edit the tests, weaken an assertion, skip a test, or change the CI config. Anthropic's long-running agent work lists "marking features passing without end-to-end tests" as a main failure mode and tells the agent "it is unacceptable to remove or edit tests"; the FDE guide calls test tampering the first factory failure mode.
- **Idea:** A **gate plane** the writer agent cannot write to:
  - The workflow declares protected paths (tests written in an earlier step, `.github/workflows/`, analyzer config, the evidence thresholds). `repo.write_file` refuses them for writer nodes; a change there needs its own node and its own gate.
  - **Tests first, then frozen:** in a test-first flow, a test-writer node writes the tests, a gate approves them, and they are frozen for the implementer (Anthropic's TDD loop).
  - **Sealed tests:** optionally a holdout set of tests or scenarios stored outside the sandbox the agent sees, run only by the verification node, so the agent cannot fit to them.
  - **Tamper detection:** any attempt to write a protected path is an event, counted per run and per workflow, and shown at the gate.
- **Already covered:** Nothing. Tool rights are per node, but not per path.
- **Open questions:** Path rules in the workflow spec or in a workspace policy? How are sealed tests stored and versioned? Does a writer still see the frozen tests (read) to know what to make pass? Yes by default; sealed tests only for evals.
- **Links:** roadmap 1.6, 4.4; [Anthropic: effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents); FDEInterviews ("protect the grader", sealed-envelope testing)

### Evals for workflows and templates (the factory tests itself)

- **Status:** ➡️ Promoted (phases 17.1–17.5; the canary with 18.1)
- **Added:** 2026-11-09
- **Problem:** A change to a template's prompts, a new model version or a new tool can make results worse, and nobody would know until users complain. Templates have no quality bar (see the template library overview), and 9.10's Architect metrics cover drafts, not runs.
- **Idea:** Evals as a first-class part of the platform:
  - **Golden cases:** per template, a set of real repos at fixed commits with a task and the expected result (tests that must pass, findings that must be found, files that must not change). Google SRE's Bronze/Silver/Gold datasets: a fast set on every change, a full set nightly.
  - **Two kinds of score:** an **output** score (deterministic checks plus an LLM judge with a rubric) and a **trajectory** score from the events log (steps, tool calls wasted, cost, time, gates hit). Google's paper names both.
  - **Replay suite for model upgrades:** before a workspace moves to a new model or provider, the suite runs on both and shows the difference.
  - **Hourly canary tasks:** a small known task runs on a schedule; a failure means the factory, not the user's repo, is broken.
  - A template or workflow version cannot be published if it scores below its previous version (a quality gate for the factory itself).
  - An Evals page: score per template and version over time, cost per passing case.
- **Already covered:** Nothing. 5.7 runs any workflow version; 9.10 measures Architect drafts.
- **Open questions:** Where do golden repos live (fixtures in this repo, or a separate eval repo)? Eval cost budget per night? Is the LLM judge a different provider from the one judged? Can users add their own cases for their own workflows?
- **Links:** roadmap 5.7, 9.9, 9.10; template library overview; [Google SRE: Golden Data, Nightly Evals](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); [Osmani: output vs trajectory evals](https://addyosmani.com/blog/new-sdlc-vibe-coding/); FDEInterviews (replay suite, canary tasks)

### Independent review through several lenses

- **Status:** ➡️ Promoted (phase 13.6)
- **Added:** 2026-11-09
- **Problem:** A reviewer agent that shares the writer's context, model and assumptions repeats the writer's blind spots (the FDE guide calls this "monoculture"). Google SRE asks for the code-writing agent to be kept apart from the agent that tests or reviews it.
- **Idea:** A `review` pattern (a composite, 6.6) with rules the engine enforces:
  - **Separate harness:** the reviewer starts with a fresh context, read-only tools, and only the spec, the diff and the evidence pack: never the writer's conversation.
  - **Several lenses in parallel:** correctness, security, performance, cloud and infrastructure, accessibility, API compatibility. Each lens is a specialist with its own instructions or skill; a `reduce` merges and deduplicates the findings (4.5). OpenAI runs one domain-specialist reviewer per lens.
  - **Cross-model:** optionally a lens runs on a different provider from the writer (once milestone 8 adds one).
  - Findings go back to the writer loop until none above a severity remain; what is left goes to the human gate as review comments next to the diff.
- **Already covered:** In part. 4.1 parallel, 4.5 reduce, 6.6 composites, 7.5's review loop. Nothing enforces separation.
- **Open questions:** Which lenses ship by default? Does a review count as evidence for earned autonomy (L2)? How many rounds before a person is asked?
- **Links:** roadmap 4.1, 4.5, 6.6, 7.5, milestone 8; [Google SRE](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); [OpenAI factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory); [GitHub Agent HQ](https://github.blog/news-insights/company-news/welcome-home-agents/) (agent review before a human sees the code)

### Circuit breakers and hard caps

- **Status:** ➡️ Promoted (phase 13.7; the monitor → fix rate limits stay parked with production feedback loops)
- **Added:** 2026-11-09
- **Problem:** Budgets stop a run that spends too much, but not one that loops (the same failing call again and again), oscillates (a fixer and a monitor undoing each other), or writes outside its task. Google SRE names "Agentic Circuit Breakers" as a required control; the FDE guide lists runaway loops as a main failure mode.
- **Idea:** The engine watches each run's events and trips a breaker that pauses the run, with the reason shown in the console banner:
  - the same tool call with the same arguments N times; the same error N times;
  - cost or tokens per step far above the node's average;
  - writes to paths outside the node's declared scope;
  - the same file changed back and forth across turns (oscillation);
  - for factory loops (monitor → fix), a rate limit on issues filed and no fixes against a change shipped in the last hour.
  Caps **refuse rather than warn**: a cap reached is a stop, not a toast. A tripped run can be resumed by a person after reading why.
- **Already covered:** In part. Budgets per run and node (milestone 3), `agents_spawned` and `max_rounds` limits (6.1, 6.2).
- **Open questions:** Thresholds per workspace or per workflow? Pause (resumable) or fail? Do breakers feed earned autonomy (a tripped breaker demotes)?
- **Links:** roadmap milestone 3, 6.1, 6.2; [Google SRE](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); FDEInterviews (circuit breaker for monitor-fixer oscillation, caps that refuse)

### Dry run for every write

- **Status:** ➡️ Promoted (phase 13.8)
- **Added:** 2026-11-09
- **Problem:** A gate before a code write shows the diff. Other writes (a Jira transition, a comment, a branch protection rule, and later a cloud change or a deploy) are approved blind. Google SRE makes "Mandatory Dry-Run Support" a rule for every agent action.
- **Idea:** Every write tool has a `plan` mode that returns what it would do, without doing it, in a shape the gate can show: "comment on PROJ-12 (text below)", "create 3 issues", "terraform plan: 2 to add, 1 to destroy", "deploy v1.4.2 to 10 % of production". The gate shows the plan; approving runs the same call for real, and the result is checked against the plan. A tool without a plan mode cannot be used behind a gate at L3 or above.
- **Already covered:** In part. 1.7 gates and 3.6 editable diffs for code.
- **Open questions:** Is the plan part of the tool manifest (10.1)? What if the world changed between plan and apply (re-plan and ask again)?
- **Links:** roadmap 1.7, 3.6, 10.1; [Google SRE: Mandatory Dry-Run Support](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/)

### Mission control: every agent and run in one live view

- **Status:** ➡️ Promoted (phase 20.2)
- **Added:** 2026-11-09
- **Problem:** The runs list shows runs one row at a time. When a team runs dozens of flows, each with orchestrated workers, nobody can see what all the agents are doing right now, steer one, or spot the one stuck. GitHub built Agent HQ around "a single command center to assign, steer, and track the work of multiple agents".
- **Idea:** A Mission control page: every live run and its workers as a board (by stage: specifying, building, verifying, waiting, shipping), with what each agent is doing now, its cost so far and its time at the current step. From it a person can pause, cancel, send a message to an agent (see "Steer a running agent"), or reassign a task. It doubles as the wall screen of the factory.
- **Already covered:** In part. Runs list v2 (11.4), Inbox (11.5), the console (11.6), 6.4 (spawned workers live).
- **Open questions:** A new page, or a mode of the runs list? How many live runs before it needs grouping?
- **Links:** roadmap 6.4, 11.4–11.6; [GitHub Agent HQ: mission control](https://github.blog/news-insights/company-news/welcome-home-agents/)

### Governance control plane

- **Status:** ➡️ Promoted (phases 20.3, 20.4)
- **Added:** 2026-11-09
- **Problem:** Limits and budgets exist, but an admin cannot say, in one place, which models, providers, agents, tools, repos and autonomy levels a workspace may use. Enterprises buying a factory ask for this first. GitHub calls its version "your agent governance layer".
- **Idea:** A Governance section in settings: allowed providers and models (and which classes may use which), allowed tools and MCP servers, repos in scope, the ceilings for earned autonomy, protected paths, data rules (no repo content to a given provider), and retention. Policies are versioned like workflows; every run records the policy version it ran under; a change to a policy is an audit event and can be required to pass a gate.
- **Already covered:** In part. Settings v2 (11.7: integrations, models and pricing, limits and budgets); 3.7 audit.
- **Open questions:** Policy as a file in a repo (GitOps) as well as a form? Per workspace only, or an organisation above workspaces?
- **Links:** roadmap 3.7, 11.7; [GitHub Agent HQ: control plane](https://github.blog/news-insights/company-news/welcome-home-agents/)

### Any vendor's agent as a node (bring your own agent)

- **Status:** ➡️ Promoted (phase 10.6)
- **Added:** 2026-11-09
- **Problem:** Teams already use Claude Code, Codex, Copilot's coding agent, Kiro or Devin. The platform's `agent` node drives a model through our own loop and tools, so those agents, and the skills and rules teams built for them, cannot be part of a flow. GitHub Agent HQ runs agents from Anthropic, OpenAI, Google, Cognition and xAI side by side.
- **Idea:** An `external_agent` node (or a provider kind): the platform starts a vendor's agent headless in the sandbox (Claude Code with `-p` and an allowed-tools list, Codex CLI, Copilot CLI), gives it the node's task and the repo, collects its output, events and cost, and applies the same gates, protected paths, breakers and evidence pack. The flow decides which agent does which step; evals compare them on the same golden cases.
- **Already covered:** In part. Milestone 8 adds a second provider (Copilot) through our own loop.
- **Open questions:** How are vendor events mapped to ours (tool calls, reasoning)? Whose keys and licences are used? Is the vendor agent's own permission system trusted, or wrapped by ours (ours, always)?
- **Links:** roadmap milestone 8, 10.1; [GitHub Agent HQ](https://github.blog/news-insights/company-news/welcome-home-agents/); Anthropic's headless fan-out ([best practices](https://www.anthropic.com/research/claude-code-best-practices))

### Spec and prototype together

- **Status:** ➡️ Promoted (phase 7.8)
- **Added:** 2026-11-09
- **Problem:** Google's paper calls spec quality "the bottleneck": a vague spec makes every later step wrong. A spec read as text is hard to judge; a person sees what they wanted only when the feature exists.
- **Idea:** The spec stage produces three things for one gate:
  - **PRODUCT.md:** the problem, users, success measures and scope, with acceptance criteria in a testable form (EARS, "When … the system shall …", as AWS Kiro does).
  - **TECH.md:** the design, the files touched, risks and the test plan.
  - **A throwaway prototype** on a branch (a UI mock or a running spike), to react to.
  The approver can comment on any of the three; the agent revises; the approved spec drives the build, and its criteria become the fail-to-pass checks of the verification gate.
- **Already covered:** In part. 7.5 has spec → gate; the Markdown upload idea lets a person bring a spec.
- **Open questions:** Is the prototype always built, or only for UI work? Is it deleted after the gate? Spec Kit compatibility (7.5) with PRODUCT/TECH files?
- **Links:** roadmap 7.4, 7.5; [Osmani on the Google paper](https://addyosmani.com/blog/new-sdlc-vibe-coding/); AWS Kiro (EARS requirements, gates between requirements, design and tasks); FDEInterviews (PRODUCT.md and TECH.md)

### Triage agent: the tracker as the control plane

- **Status:** ➡️ Promoted (phase 18.3)
- **Added:** 2026-11-09
- **Problem:** A factory needs a steady intake. Issues arrive vague, duplicated or not ready, and a person sorts them before any agent can start. OpenAI's Symphony makes "the tracker the control plane": work enters the factory by moving a ticket.
- **Idea:** A read-only triage workflow on every new issue (Jira or GitHub): find duplicates, ask for missing details, estimate size and change class, and label it `ready-to-implement`, `ready-to-spec`, `needs-info` or `wait`. A label (7.3) starts the matching flow. The triage agent's precision (labels a person later changed) is measured and shown.
- **Already covered:** In part. 7.2 reads Jira, 7.3 starts runs from a status or label.
- **Open questions:** Does triage write labels directly (a low-risk write, earned autonomy) or propose them? GitHub issues as well as Jira?
- **Links:** roadmap 7.2, 7.3; planning templates above; [awesome-software-factories (Symphony)](https://github.com/varun1505/awesome-software-factories); FDEInterviews (triage labels)

### PR shepherd: the agent follows its PR until it is merged

- **Status:** ➡️ Promoted (phases 18.5, 18.6)
- **Added:** 2026-11-09
- **Problem:** A run ends when it opens a PR. Then CI fails, a reviewer comments, main moves on and the branch conflicts, and a person has to pick it up. At OpenAI the agent "babysits" a PR until it is green and addresses review comments.
- **Idea:** After the PR is opened, the run stays alive in a light "shepherding" state: it watches CI, fixes failures (reading the job logs), answers or applies review comments (7.6), rebases when main moves, and reports when the PR is mergeable. Each push goes through the same evidence pack; the human merge stays human.
- **Already covered:** In part. 7.6 (review comments resume the run); the "Fix a failing CI build" template.
- **Open questions:** How long does a shepherd live (a timeout, like gate expiry 11.3)? Is its cost charged to the run? Needs CI log access (🟡).
- **Links:** roadmap 7.6, 11.3; [OpenAI factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory)

### Deploy shepherd: progressive rollout, error budgets, fix-forward

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Parked:** with the AI software factory vision (2026-11-10). It needs a mission change before it can be a phase: deploying to production is beyond v1's reviewable PR.
- **Problem:** Nothing in the platform reaches production. OpenAI gives its deploy agent one instruction: "Handhold this change until it is safely and fully rolled out into production." Google SRE recommends adaptive progressive rollouts and fix-forward over binary rollbacks.
- **Idea:** A deploy step, always behind a gate for production:
  - triggers the team's own pipeline (GitHub Actions, Azure DevOps, Argo CD), never deploys by itself;
  - rolls out in stages (canary → 10 % → 50 % → 100 %) behind a feature flag where the app has one;
  - builds a **per-change dashboard** of the metrics the change could affect, and watches it at each stage;
  - on a regression: pauses, proposes a fix-forward PR or a rollback (a person chooses), and records it;
  - **error budgets:** when a service's budget is spent, the factory stops merging auto-approved changes to it.
- **Already covered:** Nothing.
- **Open questions:** Is this in the mission at all (production is outside v1 today)? Which monitoring sources first (Azure Monitor, Prometheus, Datadog)? Does the factory own feature flags or use the team's (LaunchDarkly, Azure App Configuration)?
- **Links:** mission non-goals; "Ticket to production" above; [OpenAI factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory); [Google SRE](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/); FDEInterviews (canary, auto-rollback, error budgets)

### Production feedback loops: production files its own work

- **Status:** 💡 Raw
- **Added:** 2026-11-09
- **Parked:** with the AI software factory vision (2026-11-10). It needs a mission change before it can be a phase: it operates production services, beyond v1's reviewable PR.
- **Problem:** Today work enters only from a person (a run started, a ticket moved). In a factory, production is also a source of work: regressions, errors, slow endpoints, incidents. OpenAI runs Perf Factory (finds latency regressions, root-causes them, proposes fixes) and Sevbot (gathers incident context and proposes mitigations but never executes them).
- **Idea:** Watchers that turn signals into intake:
  - **Regression watcher:** reads alerts and metrics, deduplicates, finds the change that caused it (provenance trailers), and files a triaged ticket or starts a fix flow.
  - **Incident assistant:** on an incident, collects logs, recent deploys and changes, and proposes mitigations in the console; it never executes them, a person picks one.
  - Safety: rate limits on what watchers file, no filing against a change shipped in the last hour, a breaker on fix-and-revert oscillation, an owner per watcher.
- **Already covered:** Nothing. Needs monitoring integrations (🟡) and scheduled or event triggers.
- **Open questions:** Which signals first (errors from Sentry or App Insights are the simplest)? Is an incident assistant in scope for an open-source self-hosted product?
- **Links:** "Circuit breakers", "Commit trailers"; [OpenAI factory: Perf Factory, Sevbot](https://newsletter.pragmaticengineer.com/p/openai-software-factory); FDEInterviews (monitoring files new deduplicated intake)

### Long-running agents with progress artifacts

- **Status:** ➡️ Promoted (phase 13.10)
- **Added:** 2026-11-09
- **Problem:** Large work (a migration, a whole feature) does not fit one agent context. Agents then declare victory early or leave half-done work undocumented. Anthropic's long-running agents work solved it with artifacts, not bigger contexts.
- **Idea:** A long-running pattern (a template or a `loop` composite):
  - an **initializer** agent writes a `features.json` (each requirement with `passes: false`), an `init.sh` that sets up and smoke-tests the app, and a `progress.md`;
  - each iteration a coding agent starts fresh: reads progress and the git log, runs the smoke test, picks **one** failing feature, implements it, and commits;
  - only the verification node may set `passes: true` (see "Protect the grader"); JSON, not Markdown, because the model is less likely to corrupt it;
  - the loop ends when all features pass or the budget is spent; the console shows features passing over time.
- **Already covered:** In part. `loop` and artifacts (4.3); the checkpointer resumes after a crash (1.3).
- **Open questions:** Does each iteration get its own branch and commit trailer? How does the console show a run of 50 iterations (a progress view instead of 50 steps)?
- **Links:** roadmap 1.3, 4.3; [Anthropic: effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

### Repo rules and context as versioned code

- **Status:** ➡️ Promoted (phase 15.1)
- **Added:** 2026-11-09
- **Problem:** Teams write rule files for their agents (AGENTS.md, CLAUDE.md, `.cursorrules`, Copilot instructions). Google's paper treats the boundary between static context (rules, docs) and dynamic context (what an agent fetches) as "an architecture decision", reviewed in a pull request and versioned like code. It is not clear the platform's agents read a repo's rule files at all.
- **Idea:** Agents read the repo's rule files by default, as data (principle 5): the root file and, as an agent works in a folder, that folder's file (the hierarchy Anthropic recommends for large repos). The console shows which rule files a turn loaded. Workspace rules (from Governance) come first and cannot be overridden by a repo file. Combined with Skills, this is the static context; the evals measure whether a rule change helped.
- **Already covered:** Not known; to check in the agent prompt builder. The Skills idea above covers reusable know-how.
- **Open questions:** Which file names are read (AGENTS.md first, CLAUDE.md, `.github/copilot-instructions.md`)? Size limit? How is a malicious rule file in an untrusted repo contained?
- **Links:** principle 5; "Skills usable in flows and agents"; [Osmani on the Google paper](https://addyosmani.com/blog/new-sdlc-vibe-coding/); [Anthropic best practices](https://www.anthropic.com/research/claude-code-best-practices); [GitHub Agent HQ: AGENTS.md as guardrails](https://github.blog/news-insights/company-news/welcome-home-agents/)

### Model routing and cost per accepted change

- **Status:** ➡️ Promoted (phase 20.5)
- **Added:** 2026-11-09
- **Problem:** Each node names a provider and model by hand. Routine steps (formatting, triage, summaries) run on the same large model as hard ones. And the cost that matters is not cost per run but cost per change a person accepted.
- **Idea:** `model: auto` on a node: a router picks a small, medium or large model from the step's kind and past results (evals), with a fallback to the larger model on failure. Cost is reported per run and **per accepted change** (runs that ended in a merged PR, including the failed attempts before it), per workflow and per change class.
- **Already covered:** In part. Cost per run and models and pricing (milestone 3, 11.7).
- **Open questions:** Rules or a learned router? Does `auto` break reproducibility (the chosen model is recorded per step)?
- **Links:** milestone 3, 11.7; "Evals for workflows"; [Osmani: route routine work to smaller models](https://addyosmani.com/blog/new-sdlc-vibe-coding/); FDEInterviews (cost per accepted change)

### Factory metrics: is the factory working?

- **Status:** ➡️ Promoted in part (phase 20.6; WIP limits per reviewer wait for users and sign-in, and its earned-autonomy parts stay parked)
- **Added:** 2026-11-09
- **Problem:** At OpenAI, PR volume grew about 10× in some systems and human review became the bottleneck. Without numbers on flow, a team cannot tell whether the factory helps or just moves the queue.
- **Idea:** A Factory page (the metrics a factory manager reads):
  - **Flow:** changes in progress per stage, time in each stage, time waiting at gates, the review backlog and its age (Little's law: backlog ÷ throughput = wait).
  - **Quality:** acceptance rate (approved without edits), reverts within N days, escaped defects, evidence-pack failures, attempts to edit protected paths, breakers tripped.
  - **Cost:** cost per accepted change, per workflow, per class, against budget.
  - **People:** gates per approver and their wait; **WIP limits** per reviewer, so the factory stops opening PRs to a person who has too many.
- **Already covered:** In part. Active and waiting time (11.2), cost (milestone 3), the edit-share idea.
- **Open questions:** Workspace admins only, or everyone? Which three numbers go on the home page?
- **Links:** roadmap 11.2, milestone 3; [OpenAI factory](https://newsletter.pragmaticengineer.com/p/openai-software-factory); FDEInterviews (metrics, Little's law, WIP limits)

### Lethal trifecta check on every workflow

- **Status:** ➡️ Promoted (phases 13.9, 20.3)
- **Added:** 2026-11-09
- **Problem:** An agent that has access to private data, reads untrusted input (an issue, a web page, a dependency's README) and can communicate outward can be made to leak the data by a prompt injection. Simon Willison calls this the lethal trifecta. Principle 5 treats content as data, but nothing checks a workflow's combination of rights.
- **Idea:** The validator (and the canvas, 5.6) flags any node or flow that holds all three legs: private data (secrets scope, private repos, internal APIs), untrusted input (web fetch, issues from outside, uploaded files) and an outward channel (web requests, comments, PRs to public repos, email). Such a flow is refused, or must remove one leg, or must put a gate on the outward step. The Governance plane can forbid the combination outright.
- **Already covered:** In part. Principle 5; per-node tool rights; the egress allowlist (10.2).
- **Open questions:** Is each tool's leg declared in its manifest? Does a gate on the outward step make the flow acceptable?
- **Links:** principle 5; roadmap 5.6, 10.2; FDEInterviews (lethal trifecta); "LLM app security review" template

### Ask a run why (chat about a run)

- **Status:** ➡️ Promoted (phase 14.4)
- **Added:** 2026-11-09
- **Problem:** "Why did it write it this way?" is the first question after any agent change, and answering it means reading the whole console. Osmani calls the gap "comprehension debt": code a team owns but no one understands. Entire Sessions lets a person ask about past sessions in chat.
- **Idea:** A chat panel in the run console: a read-only agent with tools over the run's record (list steps, read a turn, read an output or diff, search events) answers questions about the run and links each answer to the turns it used. Later, across runs: "haven't we solved this before?" searches past runs in the workspace, and a new run can start with what earlier runs decided.
- **Already covered:** In part. 11.8 shows agent turns like a chat (display only); the Entire ideas above (trailers, why beside the diff).
- **Open questions:** Who pays for the questions (the run's budget or a workspace budget)? Are secrets redacted from the events log before an agent reads it? Is the answer kept with the run?
- **Links:** roadmap 11.8; the Entire ideas above; [Entire Sessions](https://entire.io); [Osmani: comprehension debt](https://addyosmani.com/blog/new-sdlc-vibe-coding/)

### Steer a running agent

- **Status:** ➡️ Promoted (phase 20.1)
- **Added:** 2026-11-09
- **Problem:** A person watching a run sees it go the wrong way and can only cancel it or wait for the gate. GitHub's mission control is built to "assign, steer, and track" agents.
- **Idea:** From the console or Mission control, a person sends a message to a running agent node. The agent loop checks a message queue between tool calls and adds the message as a user turn (as data, from a named person). Messages are events, kept in the record and the audit log. At a gate, "reply with feedback" sends the step back with the message instead of only approving or rejecting.
- **Already covered:** In part. Gates with edits (3.6); 7.6 (a PR comment resumes the run).
- **Open questions:** What if the message arrives as the step ends (apply to the next step, or reopen)? Who may steer (the run's owner, any member)? Durability across a worker restart (1.3)?
- **Links:** roadmap 1.3, 3.6, 7.6; "Mission control"

### Digital twins of external services for safe testing

- **Status:** ➡️ Promoted (phase 17.6)
- **Added:** 2026-11-09
- **Problem:** Flows that touch Jira, GitHub, Slack or a cloud API cannot be tested or evaluated without touching the real service. The FDE guide describes "Digital Twin Universe" clones of SaaS APIs for factory testing.
- **Idea:** Recorded or simulated twins of the external services the platform talks to (GitHub, Jira, cloud read APIs), used by evals, e2e tests and dry runs. A run can be started against twins only ("rehearsal mode"), so a team sees what a new workflow would do to their tracker and repo before letting it.
- **Already covered:** In part. The e2e suite's fakes (see the local e2e notes).
- **Open questions:** Build our own fakes or record and replay real traffic? How do twins stay in step with the real APIs?
- **Links:** "Evals for workflows", "Dry run for every write"; FDEInterviews (digital twins)

### Users, sign-in and roles

- **Status:** 💡 Raw
- **Added:** 2026-11-10
- **Problem:** The platform has no users. A deployment sits behind an authenticating proxy (mission, v1 decisions), the audit log's actor is "System" or "—" ("names come with sign-in"), and nobody can be told apart. Several roadmap phases name a person: an approver in commit trailers (14.1), who may publish a template (15.2), who sent a message to an agent (20.1), who may change a policy (20.3); and a limit on the gates waiting per approver (from "Factory metrics") needs one.
- **Idea:** Sign-in through the team's identity provider (OIDC: Entra ID, GitHub, Google), workspace members with roles (admin, maintainer, approver, viewer), the actor of every audit event, and gates assigned to people or roles.
- **Already covered:** Nothing. Found while promoting ideas to Milestones 12–20 on 2026-11-10: the phases above work with the workspace as the actor until this exists.
- **Open questions:** Before or after the SaaS deployment (10.5), which needs it for tenants? Does the authenticating proxy's identity (a header) count as a first step? Roles fixed or configurable?
- **Links:** mission v1 decisions; roadmap 3.7, 10.5, 14.1, 15.2, 20.1, 20.3; "Factory metrics"

### Host repos ourselves (a forge for agents)

- **Status:** 🗑️ Dropped
- **Added:** 2026-11-09
- **Problem:** Entire (2026) is building a Git forge for agent-written code, which raises the question of whether we should host repos too.
- **Idea:** None; recorded so it is not raised again.
- **Reason dropped:** GitHub is the v1 host and other hosts come later as adapters (mission non-goals); a forge is a different product. We integrate with forges instead.
- **Links:** mission "Non-goals (v1)"
