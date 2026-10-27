# Workspaces + connections; encrypted secrets (local KMS)

Roadmap phase: 1.4
Branch: plan/1.4-workspaces-encrypted-secrets

## Context
Today the Claude key lives in the worker's environment (`ANTHROPIC_API_KEY`), and one `AsyncAnthropic` client is shared by every run (`packages/worker/src/agentic_worker/main.py`, `runtime_factory`). The settings comment says "encrypted per-workspace keys come in phase 1.4". This phase does that. Runs belong to a workspace, the workspace holds a Claude connection, and the key is stored encrypted and decrypted only by the worker that runs it.

It depends on these phases, all done:
- 0.5/0.6: the `runs` table and `POST /runs`.
- 0.7: the Claude adapter (`ClaudeRuntime`).
- 0.8: the web app, which gets a settings page here.
- 1.3: the lease-based worker, which now builds a runtime per run.

It unblocks:
- 1.5: the GitHub App installation is stored per workspace as a connection.
- 6.1: the Jira OAuth tokens are stored with the same encryption.
- 7.3: picking a provider per workspace builds on connections.
- 9.5: the cloud KMS replaces the local key provider behind the same interface.
- The MVP click-through: a user pastes their key in the browser instead of editing `.env`.

Principles and stack choices that apply:
- **Tech stack, "Security & secrets":** "Secrets are encrypted with a KMS key per workspace (cloud KMS in production; a local key file in dev). They never appear in logs or agent context."
- **Tech stack, "Agent runtime":** Claude auth is the "user's API key, encrypted with a KMS key per workspace".
- **Tech stack, "Tool layer":** "Credentials stay inside the tool servers. Agents never see them." The key goes to the Anthropic client only, never into a prompt, a tool or an event.
- **Transparency (6):** connection changes are visible. The key never is.
- **Small, verifiable steps (7):** one default workspace, one provider. Users, membership and auth come later.

## Scope
### In scope
- **Crypto (new package `agentic_secrets`):**
  - A `KeyProvider` protocol: `wrap(dek) -> WrappedKey` and `unwrap(WrappedKey) -> dek`, with a `key_id` so a later KMS key or a rotated key can be told apart.
  - `LocalKeyProvider`: reads a 32-byte master key from `MASTER_KEY_FILE`. The master key wraps data keys with AES-256-GCM.
  - Envelope encryption: each workspace gets its own random data key (DEK), stored wrapped. Secrets are encrypted with AES-256-GCM under that DEK. The associated data is `workspace_id` + `connection_id`, so a ciphertext copied to another row fails to decrypt.
  - `python -m agentic_secrets generate-key <path>` creates a master key file. It never overwrites an existing file.
  - A redaction registry plus a `logging.Filter` that replaces every live secret value with `[REDACTED]` in messages and exception text.
- **Schema (Alembic, migration 0007):**
  - `workspaces`: `id`, `name`, `wrapped_dek` (nullable until the first secret is written), `key_id`, timestamps.
  - `connections`: `id`, `workspace_id`, `provider` (`claude` for now), `secret_ciphertext`, `secret_nonce`, `key_hint` (the last 4 characters), timestamps. There is one connection per workspace and provider (unique).
  - The migration inserts one default workspace with a fixed id.
  - `runs.workspace_id` is a foreign key. Existing rows are backfilled to the default workspace, then the column is set to `NOT NULL`.
- **Store:** `get_workspace`, `list_workspaces`, `put_connection` (create or replace, creating the workspace DEK on first use), `list_connections` (without ciphertext), `delete_connection`, `load_secret(workspace_id, provider) -> SecretStr | None`.
- **API:**
  - `GET /workspaces` returns the default workspace.
  - `GET /workspaces/{id}/connections` lists provider, hint and timestamps.
  - `PUT /workspaces/{id}/connections/claude` takes `{ "api_key": ... }`, is write only and returns the hint.
  - `DELETE /workspaces/{id}/connections/claude`.
  - `POST /runs` takes an optional `workspace_id`, which defaults to the default workspace.
  - The key never appears in a response, an error body or a validation error echo.
  - Without `MASTER_KEY_FILE`, the connection writes return `503` with a clear message. Runs on the fake runtime still work.
- **Worker:**
  - With `AGENTIC_RUNTIME=claude`, each run loads its workspace's Claude key, builds its own `AsyncAnthropic` client and closes it when the run ends.
  - A missing connection ends the run with `run_failed` and the reason "workspace has no Claude connection".
  - `ANTHROPIC_API_KEY` is removed from the worker settings, `.env.example` and compose.
  - The decrypted key is registered for redaction while the run is alive. The worker's event sink wrapper redacts payloads before writing `run_events`, as a second line of defence.
- **Compose:**
  - A one-shot `keygen` service creates the master key in a named volume if it is missing.
  - The API and the worker mount that volume read only and set `MASTER_KEY_FILE`.
  - `docker compose up` keeps working with no manual step.
- **Web:**
  - A `/settings` page shows the default workspace's Claude connection (hint and last updated).
  - It has a password field to add or replace the key and a button to delete it.
  - The home page links to it.
  - The OpenAPI client (`web/src/api/schema.d.ts`) is regenerated.
- **Docs:** a README section on secrets (where the master key lives, how to add a key, what is never logged) and a CHANGELOG entry.

### Out of scope
- Users, login, workspace membership, more than one workspace in the UI: no phase owns this yet (it is needed before 9.5).
- Cloud KMS, and master key rotation tooling: 9.5. The `key_id` column and the `KeyProvider` interface keep the way open.
- Checking the key with a live Anthropic call when it is saved: see Open questions.
- Copilot and per-node provider selection: 7.2/7.3.
- The GitHub App and Jira credentials: 1.5 and 6.1 reuse this storage.
- An audit log of connection changes: 3.7. This phase only keeps `created_at`/`updated_at`.
- A Playwright test and a manual compose demo: not chosen for validation in this phase.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Backend plus a small settings page, one default workspace, no auth | This was the user's choice. It meets "Done when" and lets the MVP be clicked through without `.env`. |
| Encryption | Envelope: master key (KEK) wraps a DEK per workspace, AES-256-GCM via `cryptography` | This was the user's choice. It matches "a KMS key per workspace". `cryptography` is already in `uv.lock`. A cloud KMS only replaces `wrap`/`unwrap`. |
| Binding | AES-GCM associated data = `workspace_id` + `connection_id` | A ciphertext moved to another row or workspace fails to decrypt instead of leaking into the wrong run. |
| Where crypto lives | New `agentic_secrets` package, used by the API and the worker | The engine and the runtime stay free of secrets and of the database. |
| Default workspace | Created by the migration with a fixed id, DEK created lazily on the first secret | The migration doesn't need the master key, and existing runs get a valid foreign key. |
| Env key | `ANTHROPIC_API_KEY` removed; the Claude runtime needs a stored connection | There is one source of truth, and "used by a run" can't pass by accident through the env. |
| Client per run | `AsyncAnthropic` built per run and closed after | Runs from different workspaces use different keys. The key is in memory only while its run is alive. |
| Key display | Write only; show only the last 4 characters | The user can tell which key is stored, and the API never returns it. |
| Master key in dev | Created by a compose `keygen` one-shot in a named volume, never overwritten | `docker compose up` stays one command, and recreating containers doesn't make stored secrets unreadable. |
| Leak defence | `SecretStr` everywhere, a redaction filter on logs, redaction of event payloads, no key in error bodies | "They never appear in logs or agent context" (tech stack). |
| Build order | Crypto → store → API → worker → UI; the env key is removed in the UI group | This was the user's choice. Each group leaves the project working, and Claude stays usable without `curl` until the page exists. |

## Open questions
- ~~**Losing the master key:**~~ Resolved in group 2. A `PUT` on a workspace whose data key cannot be unwrapped gives it a new data key and drops the connections nobody can read any more, so storing the key again is the recovery. A run whose key cannot be decrypted fails with "the workspace's Claude key cannot be decrypted; store it again". No 409 is needed in the API, since it never decrypts.
- **Checking the key on save:** a cheap Anthropic call (for example `models.list`) would catch typos early, but adds a network call and a failure mode to `PUT`. The current choice is to not check it, so a bad key shows up as a `run_failed` with the provider's error. Revisit when the settings page is used.
- **Master key backup:** if the `secrets` volume is deleted, stored keys must be entered again. Backup is an ops question for 9.5.
- **Testcontainers on Docker Desktop (Windows):** the Ryuk reaper container can fail with "Port mapping … 8080 is not available". Run the integration tests with `TESTCONTAINERS_RYUK_DISABLED=true` locally; CI (Linux) is not affected.
- **Live Claude proof:** validation uses a fake Anthropic client that captures the key it was built with. No manual run against the real API was chosen. Run one before the MVP demo.
