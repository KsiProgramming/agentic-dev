# `tool` primitive + `repo` write tools + worktree/branch per writer

Roadmap phase: 1.6
Branch: plan/1.6-tool-primitive-repo-writes

## Context
After 1.2, agents can read a run's clone through the `repo` MCP server, but they can't change it. The clone is root-owned and read only, the `alpine:3.20` sandbox image has no git, and the spec has only `agent` and `sequence` nodes. This phase lets a node write files and commit them on its own branch, `agent/<run>/<node>`, inside the sandbox. It also adds the deterministic `tool` primitive, which runs one tool with no model.

It depends on these phases, all done:
- 1.1: the sandbox and its hardened container.
- 1.2: the `repo` server, the `McpToolExecutor` bridge and the fake runtime's schema `examples`.
- 1.3: resume recreates the sandbox.
- 0.2/0.4: the spec union and the compiler.

It unblocks:
- 1.7/1.8: a gate before push, then `github.openPR` on the writer's branch.
- 1.10/3.1/5.3: parallel writers, each on its own worktree, merged later.
- 1.11: the docs template writes files.
- 3.4: deterministic tool nodes (linters, scanners) build on `tool`.

Principles that apply:
- **Open, but safe by construction (2):**
  - Writes stay inside the node's own worktree. `..`, absolute paths, symlink escapes and anything under `.git` are refused.
  - Each file is capped in size.
  - The container keeps `network_mode=none`, so a commit is local only.
- **Humans approve irreversible actions (3):** nothing is pushed in this phase. A local commit in a throwaway sandbox can be undone. Push and PR come in 1.7/1.8, behind a gate.
- **Tools live in the platform (4):** the write tools are added to the same `repo` MCP server, and adapters reach them only through `ToolExecutor`.
- **Repo content is data (5):** git runs with hooks disabled (`core.hooksPath=/dev/null`), no signing and a fixed platform identity, so the repo's own config can't run code.
- **Small, verifiable steps (7):**
  - Two write tools only.
  - Grants come from the spec, not from manifests.
  - No push.

## Scope
### In scope
- **Sandbox image with git:**
  - A pinned `packages/sandbox/Dockerfile`: `alpine:3.20` plus `git`, with the non-root sandbox user.
  - Compose builds it as `agentic-sandbox:local`, and CI builds it before the Docker tests.
  - The `SANDBOX_IMAGE` default changes to that image.
- **Clone layout:**
  - The tar copied into the container still holds a root-owned, read-only base checkout at `/workspace/repo`.
  - Its `.git` and an empty `/workspace/worktrees/` belong to the sandbox user, so `git worktree add` can run without capabilities.
  - The fake sandbox mirrors this layout in its temp dir, using host git.
- **`Sandbox` additions:**
  - `exec(..., cwd=)` runs a command in a worktree.
  - `put_file(path, data)` writes bytes into a staging dir that the sandbox user owns. It exists because file content can't travel as an argv argument, which is limited to about 128 KiB.
- **Worktree per writer:**
  - A **writer** is a node whose `tools` (agent) or `tool` (tool node) name a write tool.
  - On a writer's first tool call, the run's tools run `git worktree add -b agent/<run-id>/<node-id> /workspace/worktrees/<node-id> HEAD` and open a `repo` server bound to that worktree, with write tools on.
  - All of that node's `repo.*` calls go there, so it reads its own writes. Every other node keeps the read-only base checkout.
- **Write tools** on the `repo` server, registered only when the server is writable:
  - `write_file(path, content)`:
    - Creates or overwrites a UTF-8 text file and creates parent directories.
    - Refuses paths that escape the worktree, paths under `.git`, directories, and content over 1 MiB.
    - Returns the path and the byte count.
  - `commit(message)`:
    - Runs `git add -A` and `git commit` with the identity `agentic-dev agent <agent@agentic-dev.invalid>`, `core.hooksPath=/dev/null` and `commit.gpgsign=false`.
    - Returns the short SHA, the branch and the changed paths. It is an error if there is nothing to commit.
  - Each tool has a schema `examples` entry, so the unscripted fake runtime writes a file and commits it.
- **Tool routing by node:** `ToolExecutor.call` gets a `node_id` keyword. `ClaudeRuntime` and `FakeRuntime` pass `request.node_id`. A run-level `RepoTools` executor sends each call to the base server, or to that node's writer server.
- **`tool` primitive:**
  - Spec shape: `{"type": "tool", "id", "tool": "<server>.<name>", "args": {…}}`, added to the `Node` union. The JSON Schema is re-exported.
  - It compiles to a LangGraph node that calls `ToolExecutor.call(tool, args, node_id=id)` and emits `node_started`, `tool_call`, `tool_result` and then `node_completed` or `node_failed`.
  - Its output text becomes the next node's input. An `is_error` result fails the node.
  - It reuses `AgentNodeResult` with `usage=None`.
- **Grants and validation:**
  - Only writers get a worktree and write tools. A non-writer that calls `repo.write_file` gets an "unknown tool" error result.
  - The API's existing rule (`repo.*` needs a `repo`, else `422`) also covers `tool` nodes.
- **Demo fixture** `write-file.json`: an agent with `repo.read_file`, `repo.write_file` and `repo.commit`, then a `tool` node running `repo.list_files`. `scripts/sandbox_demo.py --spec` runs it.
- **Docs:** the README section on repo tools covers the write tools, the branch naming and the grant rule.

### Out of scope
- Push, PR and the gate in front of them: 1.7 and 1.8.
- Keeping a writer's branch across a worker restart. On resume the sandbox is recreated, and the writer node runs again from a fresh worktree (1.3 behaviour). This comes back once a branch has to survive, at 1.8 at the latest.
- `delete_file`, `move_file`, patch/edit tools and git history tools: add them when a template needs them.
- Manifest-based tool grants and read-only enforcement per node type: 4.3.
- Merging writer branches: 5.3.
- Parallel writers running at the same time. The layout supports it, but `parallel` and `map` arrive in 1.10/3.1.
- A dedicated commit run event or monitor view. The commit shows up as a `tool_result` for now, and 2.5 adds the view.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where git runs | In the sandbox, from a small pinned image (alpine + git) | The commit happens where the agent's files are, with no network and no host access (tech stack, "Sandbox"). Running git on the worker host was considered and rejected because it splits the logic and moves repo writes out of the sandbox. |
| Write tool set | `write_file` + `commit` | This is the smallest set that meets "Done when". The other file operations wait for a template that needs them. |
| Worktree timing | Created lazily on a writer's first tool call | Readers and runs with no writers pay nothing. It needs no new engine hook. |
| Branch name | `agent/<run-id>/<node-id>` from the clone's `HEAD` | It is fixed by the tech stack. Node ids are already ref-safe (0.2). |
| Who is a writer | Derived from the spec: the node lists a write tool | User choice: grants per node from the spec now, from manifests in 4.3. |
| Routing | `node_id` keyword on `ToolExecutor.call`, plus a run-level `RepoTools` router | Each MCP server stays bound to one directory, which is the same safety argument as in 1.2. The protocol change is one keyword. |
| File transfer | `Sandbox.put_file` into a staging dir, then a confined `mv` | Content can be up to 1 MiB, which is over the argv limit. Docker's `put_archive` can't write to tmpfs, so the staging dir lives on the volume. |
| `tool` node result | Reuse `AgentNodeResult` (`usage=None`) | No state migration. Rename it to `NodeResult` once a third node kind needs that. |
| Commit identity and safety | Fixed platform identity, hooks off, no signing | Repo content is data (5). The repo's config must not run code or need keys. |
| Resume | Recreate the worktree, and the writer runs again | It keeps 1.3's rule. Nothing has been pushed yet, so nothing is lost. |

## Open questions
- ~~Can `git worktree add` with a shallow clone (`--depth 1`) and a sandbox-user-owned `.git` inside a root-owned checkout work with no capabilities?~~ Resolved in group 2: yes. git refuses the root-owned checkout as "dubious ownership" unless the command passes `-c safe.directory=/workspace/repo`, which `add_worktree` does. Inside the worktree, which the sandbox user owns, git needs nothing extra. The fallback was not needed.
- Should a run summary list the branches each writer produced, for 1.8? It is not needed for "Done when". Decide in 1.8.
