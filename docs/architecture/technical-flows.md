# Technical flows

How the system carries out each [business flow](business-flows.md): the requests, the processes involved, what is written where, and what happens on failure. Read the [architecture overview](overview.md) first for the containers and packages named here.

---

## 1. Run lifecycle

A run's `status` lives on its `runs` row. It is a **projection** of the run's append-only events, written by the event sink in the same transaction as each event.

```mermaid
stateDiagram-v2
    [*] --> queued: POST /runs (or rerun)
    queued --> running: worker claims lease → run_started
    running --> waiting: gate_waiting (lease released, sandbox kept)
    waiting --> queued: POST /runs/{id}/approvals
    queued --> running: worker claims → run_resumed
    running --> queued: worker dies (lease expires) / graceful stop
    running --> completed: run_completed
    running --> failed: run_failed (error, policy limit, budget, MAX_ATTEMPTS)
    queued --> cancelled: cancel requested
    running --> cancelled: cancel requested → run_cancelled
    waiting --> cancelled: cancel requested / gate expired
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

Six statuses only. "Expired" is a cancelled run whose `run_cancelled` event carries `{reason: "Approval expired", expired: true}`, so no filter or badge needs a seventh status.

---

## 2. Starting and executing a run

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as API
    participant PG as Postgres
    participant R as Redis
    participant W as Worker
    participant S as Sandbox
    participant M as Model provider

    B->>A: POST /runs {template | stored_workflow | spec, repo, input, budget_usd?}
    A->>A: build spec, validate (schema, ports, policy vs workspace limits)
    A->>PG: INSERT runs (status=queued, spec, frozen policy) + audit_events
    A->>R: LPUSH runs:queue <run_id>
    A-->>B: 201 {run_id, events_url}
    B->>A: GET /runs/{id}/events (SSE)
    W->>R: BRPOP runs:queue
    W->>PG: UPDATE runs SET worker_id, lease_expires_at WHERE status='queued' AND no lease
    W->>PG: read spec, policy, workspace key (encrypted)
    W->>W: unwrap DEK, decrypt key, register for redaction
    W->>S: create container, copy clone into /workspace
    W->>W: compile spec → LangGraph, wire MCP tool servers
    loop each node
        W->>M: Messages API (system = role + instructions, input as data)
        M-->>W: stream text / tool_use
        W->>S: exec tool command (repo.read_file, scan.lint, …)
        W->>PG: INSERT run_events + update summary columns, NOTIFY
        W->>PG: checkpoint node state
        PG-->>A: NOTIFY run_events
        A-->>B: SSE event
    end
    W->>PG: run_completed, release lease
    W->>S: remove container + volume
```

Key points:

- **Only the run id travels through Redis.** The spec, input and limits are read from Postgres, so a lost Redis message cannot change what runs, and a run is never executed twice: the conditional `UPDATE` that claims a lease succeeds for exactly one worker.
- **The policy is frozen at creation** (`runs.policy`). Resumes and later policy changes never move the limits a run was given.
- **Validation runs twice**: before the run (`422` on a violation) and inside the engine while it runs (agents spawned and alive, wall time, budget).
- Text deltas are buffered for 250 ms before they are written, so the log holds messages rather than thousands of tokens; the browser merges deltas into one growing message per agent turn.

---

## 3. Durable execution and recovery

```mermaid
sequenceDiagram
    participant W1 as Worker 1
    participant PG as Postgres
    participant W2 as Worker 2

    W1->>PG: claim lease (TTL 30 s)
    loop every 10 s
        W1->>PG: renew lease
    end
    W1->>PG: node A completed + checkpoint
    Note over W1: crash / OOM / node drained
    W2->>PG: find queued|running run with expired lease<br/>(database clock, SKIP LOCKED)
    W2->>PG: reclaim, attempt += 1
    W2->>W2: open a fresh sandbox, restore artifacts
    W2->>PG: resume from last checkpoint → node B
```

- **What is durable:** every completed node's state (LangGraph Postgres checkpointer), every event, every artifact version. A node that was mid-flight runs again from its start.
- **Expiry uses the database clock**, so worker clock skew cannot cause two owners.
- **Crash loops stop:** a run claimed more than `MAX_ATTEMPTS` times (default 3) fails with a reason.
- **Graceful stop:** a stopping worker cancels its graph without ending the run and releases the lease, so another worker resumes it at once.
- **Spend survives restarts:** the budget meter starts from the run's stored spend, so earlier attempts and time before a gate count.

---

## 4. Gates: pause, review, resume

```mermaid
sequenceDiagram
    participant W as Worker
    participant PG as Postgres
    participant A as API
    participant U as Approver
    participant R as Redis

    W->>PG: gate_waiting {title, files changed, expires_at}
    W->>PG: status=waiting, release lease (sandbox KEPT)
    U->>A: GET /runs/{id}/gate (diff of writers' branches)
    U->>A: POST /runs/{id}/approvals {decision, comment, edits[]}
    A->>PG: INSERT approvals (one per run+node) + audit, status=queued
    A->>R: LPUSH run id
    W->>PG: claim → run_resumed
    W->>W: reattach kept sandbox, LangGraph resume with decision
    W->>W: gate node commits edits on writer branch → gate_decided
```

- The gate is a LangGraph `interrupt()`. No worker holds a waiting run, so a gate can wait for days at no compute cost.
- **Expiry:** every worker sweeps every `GATE_SWEEP_S` (30 s) for runs whose `gate_expires_at` has passed, marks them cancelled with the reason, and queues them so a worker ends them and removes the sandbox. Expiry is a write, not something computed when the run is read, so a run nobody opens still expires.
- Edits are committed by the gate node itself, so they are checkpointed with the decision and the next node (`github.openPR`) needs no special case.

---

## 5. Delivering a change: from sandbox to pull request

The sandbox has **no network and no credentials**, so commits leave it as data and are pushed by the worker.

```mermaid
sequenceDiagram
    participant Ag as Writer agent
    participant S as Sandbox (no network)
    participant W as Worker
    participant GH as GitHub

    Ag->>S: repo.write_file / repo.commit (worktree agent/<run>/<node>)
    Note over S: commit as sandbox user on own branch
    W->>S: git bundle <base>..<branch>
    S-->>W: bundle bytes
    W->>GH: mint installation token (App JWT, short-lived)
    W->>W: throwaway repo: depth-1 fetch base, fetch bundle,<br/>check branch descends from base
    W->>GH: git push (create branch only; token as HTTP header via env)
    W->>GH: POST pulls (head=agent/<run>/<node>, base=ref)
    W->>W: pr_opened {url}
```

Safety properties of the push:

- The token reaches git only through `GIT_CONFIG_*` environment variables as an HTTP header: never argv, a remote URL or a config file. git reads no system or user config, runs no hooks and never prompts.
- The push may only **create** the branch (or find it already at the same commit, for a retried node). It cannot force-push or touch another branch.
- Error messages carry git's reason, never the token.

**New repositories** (`github.createRepo`): the gated node creates an organisation repo with GitHub's `auto_init`, the attempt ends `suspended`, and the worker immediately starts a new attempt that clones the new repo through the normal path.

---

## 6. Live event streaming

```mermaid
flowchart LR
    W["Worker<br/>PostgresEventSink"] -- "INSERT run_events<br/>+ UPDATE runs summary<br/>+ NOTIFY (same tx)" --> PG[("Postgres")]
    PG -- "LISTEN run_events<br/>(one connection per API process)" --> L["API listener"]
    L -- "wake subscribers" --> SSE["GET /runs/{id}/events"]
    SSE -- "read events after last seq" --> PG
    SSE -- "text/event-stream<br/>id: seq" --> B["Browser EventSource"]
```

- Each event has a per-run `seq` (unique with the run id), which is the SSE `id`. A reconnecting browser sends `Last-Event-ID` and receives exactly the events after it, read from Postgres. Notifications only say "something changed", so a dropped notification costs latency, never data.
- `GET /runs/stream` and `GET /runs/counts` keep the runs list and sidebar counts live the same way.
- Event types include `run_started`, `node_started`, `text_delta`, `reasoning_delta`, `tool_call`, `tool_result`, `usage`, `map_item_*`, `parallel_branch_*`, `loop_*`, `artifact_written`, `gate_waiting`, `gate_decided`, `pr_opened`, `repo_created`, `policy_limit_exceeded`, `node_completed|failed|cancelled`, `run_completed|failed|cancelled|resumed`.

---

## 7. Agent execution and tools

```mermaid
flowchart LR
    E["Engine: agent node"] -- "AgentRequest<br/>role, instructions, input,<br/>tools, model, output_schema" --> RT["AgentRuntime<br/>(Claude adapter)"]
    RT -- "AgentEvents" --> E
    RT -- "tool_call" --> TR["RunTools router"]
    TR -- "repo.*" --> RS["repo MCP server"] --> SB["Sandbox exec"]
    TR -- "scan.*" --> SC["scan MCP server"] --> SB
    TR -- "artifacts.*" --> AR["artifacts MCP server"] --> PG[("Postgres")]
    TR -- "github.*" --> GS["github MCP server"] --> GH["GitHub (worker side)"]
```

- **Prompt-injection defence by structure.** Role and instructions are the system prompt. Repo content, previous outputs and tool results reach the model only as input marked as data (an `<input>` block, `tool_result` blocks), never as instructions.
- **Tools are granted per node.** An agent sees only the tools its spec names; audit agents get read tools only. Writer nodes (those that name `repo.write_file` or `repo.commit`) each get their own worktree; readers see a root-owned, read-only checkout.
- **Strict arguments.** `strict_tool` refuses unknown arguments. Every tool takes an optional `description` (why the call is made), shown in the console.
- **Typed ports.** If a node declares `output_schema`, the engine asks for JSON, parses it and validates it with `jsonschema` (2020-12, local `$ref`s only, so validating never fetches a URL). A wrong shape fails at that edge with a JSON pointer.
- **Artifacts.** Nodes declare `writes` and `reads`; every version is stored in `run_artifacts` and copied read-only into the sandbox. There is no write tool, so the validator sees every writer before the run.

---

## 8. Workflow editing: graph operations and versions

```mermaid
sequenceDiagram
    participant C as Canvas (browser)
    participant A as API
    participant E as Engine
    participant PG as Postgres

    C->>C: edits kept as ops; browser mirror of apply_ops draws them
    C->>A: POST /workflows/{id}/validate (debounced)
    A->>E: validate(spec) → issues[]
    A-->>C: 200 {issues} (shown on nodes)
    C->>A: PATCH /workflows/{id} {base_version, ops[]}
    A->>PG: SELECT workflow FOR UPDATE (row lock)
    alt base_version ≠ latest
        A-->>C: 409 (re-apply ops on latest)
    else
        A->>E: apply_ops → new spec; schema check
        A->>PG: INSERT workflow_versions (spec, ops, base_version)
        A-->>C: 200 {version}
    end
```

- Operations: `addNode`, `removeNode`, `connect`, `disconnect`, `setParam` (with `wrap` and `extract` planned). They address nodes by id over the spec's tree, so ids stay stable as the tree changes (unlike JSON Patch array positions).
- Versions are append-only (a database trigger refuses `UPDATE`/`DELETE`). A restore copies an old spec as the next version with `restored_from`.
- A version must match the schema but may hold other issues (work in progress); **runs** refuse any version with issues.

---

## 9. Secrets: storing and using a model key

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as API
    participant K as KeyProvider (master key)
    participant PG as Postgres
    participant W as Worker

    B->>A: PUT /workspaces/{id}/connections/claude {api_key}
    A->>A: verify key with provider
    alt workspace has no data key
        A->>A: DEK = random 256-bit
        A->>K: wrap(DEK) → wrapped_dek, key_id
        A->>PG: workspaces.wrapped_dek
    end
    A->>A: AES-256-GCM(DEK, key, AAD = workspace + connection id + provider)
    A->>PG: connections (nonce, ciphertext, key_hint = last 4)
    A-->>B: {provider, key_hint}
    Note over W: at run start
    W->>K: unwrap(wrapped_dek)
    W->>W: decrypt key, register with redactor,<br/>give to this run's Anthropic client only
```

- The associated data binds a ciphertext to its row, so a ciphertext copied to another workspace or provider fails to decrypt.
- The master key never leaves its `KeyProvider`; swapping the local key file for a cloud KMS is a new provider class, not a schema change.
- Redaction is a second line of defence: any registered value is replaced with `[REDACTED]` in log records and event payloads while it is held.

---

## 10. GitHub App installation

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as API
    participant R as Redis
    participant GH as GitHub

    B->>A: POST /workspaces/{id}/connections/github/install
    A->>R: SET state → workspace (TTL 10 min)
    A-->>B: https://github.com/apps/<slug>/installations/new?state=…
    B->>GH: choose account and repositories
    GH-->>B: redirect to Setup URL
    B->>A: GET /github/setup?installation_id=…&state=…
    A->>R: GETDEL state (single use)
    A->>GH: GET installation (App JWT) — is it ours?
    A->>PG: connections (provider=github, external_id, account_login)
    A-->>B: 302 /settings?github=connected
```

A GitHub connection holds **no secret**: only the installation id. Tokens are minted on demand from the App's private key and expire within an hour. Hardening still to do (users and OAuth during install, narrower token scopes) is listed in the [security model](../security/security-model.md#7-known-gaps-and-hardening-roadmap).

---

## 11. Cost accounting and limits

1. The adapter emits one `usage` event per provider call, with input, output and cache tokens.
2. It prices that call from the workspace's price table (list prices dated by `PRICES_AS_OF`, plus overrides) and writes `estimated_usd` into the event. **The logged price never changes.**
3. The event sink adds the totals to the `runs` row; a usage with no price marks the run's cost incomplete.
4. The engine's budget meter adds each priced usage. When spend reaches the budget, running nodes are cancelled and the run fails with `policy_limit_exceeded {limit: "budget_usd"}`.
5. Wall time counts active time only: the worker compares the run's active seconds (stored stretches plus this attempt) with `wall_time_s`.
