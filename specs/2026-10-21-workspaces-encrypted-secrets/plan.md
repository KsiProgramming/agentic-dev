# Plan: Workspaces + connections; encrypted secrets (local KMS)

The env-key path keeps working until group 5, where the settings page replaces it. So after every group there is a way to run on Claude, and the build stays green.

## 1. Crypto package (`agentic_secrets`)
- [ ] Add `packages/secrets` to the `uv` workspace with `cryptography` and `pydantic` as dependencies. Add it to the ruff, pyright and pytest config.
- [ ] `keys.py`: the `KeyProvider` protocol, `WrappedKey(key_id, nonce, ciphertext)`, and `LocalKeyProvider.from_file(path)`. A file that is not exactly 32 bytes raises a clear `SecretsConfigError`.
- [ ] `envelope.py`: `new_dek()`, `encrypt(dek, plaintext, aad) -> (nonce, ciphertext)`, `decrypt(dek, nonce, ciphertext, aad) -> SecretStr`. A wrong key, a wrong AAD or tampered bytes raise `SecretDecryptError`.
- [ ] `redact.py`: a process-local registry (`register(SecretStr)` as a context manager), `redact(text)`, and `RedactingFilter(logging.Filter)`, which redacts `msg`, `args` and the exception text.
- [ ] `__main__.py`: `generate-key <path>` writes 32 random bytes with `O_EXCL` and mode 0600, and refuses to write if the file exists.
- [ ] Unit tests: round trip, tampering, wrong AAD, wrong master key, key file checks, redaction of messages and tracebacks, `generate-key` not overwriting.

## 2. Schema and store
- [ ] `agentic_store/models.py`: `Workspace` and `Connection` models. Add `Run.workspace_id`.
- [ ] Alembic `0007_workspaces_connections.py`:
  - create both tables;
  - insert the default workspace (`DEFAULT_WORKSPACE_ID`, a constant in `agentic_store`);
  - add `runs.workspace_id`, backfill it and set it to `NOT NULL`;
  - downgrade drops all of it.
- [ ] `agentic_store/connections.py`:
  - `list_workspaces`, `get_workspace`;
  - `put_connection(workspace_id, provider, secret, keys)`, which creates the workspace's DEK on first use (in the same transaction) and replaces an existing connection;
  - `list_connections`, which returns no ciphertext;
  - `delete_connection`;
  - `load_secret(workspace_id, provider, keys)`.
- [ ] `create_run` takes `workspace_id`. `StoredRun` carries it.
- [ ] Tests (Testcontainers Postgres):
  - store round trip;
  - replace keeps one row;
  - a ciphertext moved to another workspace fails to decrypt;
  - `test_migrations` upgrades and downgrades through 0007 with an existing run row.

## 3. API
- [ ] `Settings.master_key_file: Path | None`. Build the `KeyProvider` at startup if it is set.
- [ ] `agentic_api/workspaces/` with `models.py` (`WorkspaceOut`, `ConnectionOut`, `PutClaudeConnection` with `api_key: SecretStr`, `min_length`) and `routes.py`:
  - `GET /workspaces`;
  - `GET /workspaces/{id}/connections`;
  - `PUT /workspaces/{id}/connections/claude`;
  - `DELETE /workspaces/{id}/connections/claude`.
- [ ] Map an unknown workspace to 404, a missing master key to 503, and `SecretDecryptError` to a 409 saying "re-enter the key". Validation errors on `PUT` don't echo the input.
- [ ] `CreateRunRequest.workspace_id: UUID | None`. An unknown id returns 404.
- [ ] Install `RedactingFilter` in the API's logging setup.
- [ ] Tests:
  - `PUT` then `GET` shows the hint and never the key;
  - a bad body doesn't echo the key;
  - 503 without a master key;
  - `DELETE`;
  - `POST /runs` with and without `workspace_id`.

## 4. Worker uses the stored key
- [ ] `WorkerSettings`: add `master_key_file`. A run uses its workspace's stored key when there is one, and falls back to `ANTHROPIC_API_KEY` until group 5 removes it.
- [ ] Change `RuntimeFactory` so it builds a runtime for one run, given the run (workspace) and its tools. For Claude:
  - load the secret;
  - register it for redaction;
  - build `AsyncAnthropic(api_key=...)`;
  - close the client and unregister the secret when the run's attempt ends (also on resume and on failure).
- [ ] A missing connection gives `run_failed` with the reason "workspace has no Claude connection", and no retries.
- [ ] The event sink wrapper in `main.py` passes payloads through `redact` before `emit`.
- [ ] Install `RedactingFilter` in the worker's `configure_logging` call.
- [ ] Compose:
  - add a `keygen` one-shot service and a `secrets` named volume;
  - mount the volume read only in `api` and `worker`, and set `MASTER_KEY_FILE`.
- [ ] Tests (`test_build_runtime.py`, `test_worker.py`):
  - a run on the Claude factory, using a fake Anthropic client class injected through the factory, receives the stored key;
  - two workspaces get their own keys;
  - a missing connection fails the run cleanly;
  - the client is closed after the run.

## 5. Settings page, env key removed, no-leak test and docs
- [ ] Remove `anthropic_api_key` from `WorkerSettings` and `ANTHROPIC_API_KEY` from `docker-compose.yml` and `.env.example`. `AGENTIC_RUNTIME=claude` without a master key is a `ConfigError` at startup.
- [ ] Regenerate `web/src/api/schema.d.ts` from the API's OpenAPI.
- [ ] `web/src/settings/claude-connection.tsx` (TanStack Query):
  - load the connections;
  - a form with a password input to save the key (cleared after saving);
  - show "Claude key ending in …abcd, updated <time>";
  - a delete button with a confirm step.
- [ ] `web/src/app/settings/page.tsx`, and a link from the home page.
- [ ] Vitest and Testing Library tests: empty state, saving (the request body contains the key, the field is cleared, the hint is shown), deleting, and an error message on 503.
- [ ] `packages/worker/tests/test_no_secret_leak.py` (see validation.md): an end-to-end run with a canary key through the API, the store and the worker. Logging is set to DEBUG.
- [ ] README "Secrets" section and CHANGELOG entry. Tick this plan, and mark the open questions resolved where they are.
