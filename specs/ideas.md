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
