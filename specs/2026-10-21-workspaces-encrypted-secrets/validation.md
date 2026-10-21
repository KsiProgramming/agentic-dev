# Validation: Workspaces + connections; encrypted secrets (local KMS)

## Done when (from roadmap)
> A Claude key is stored encrypted and used by a run; it never appears in logs

To check this:
- **Stored encrypted:** after `PUT /workspaces/{id}/connections/claude`, the `connections` row holds AES-GCM ciphertext, and the workspace holds only a wrapped DEK. Neither contains the key's bytes.
- **Used by a run:** a run on the Claude runtime builds its Anthropic client with exactly that key. No env key is involved, because `ANTHROPIC_API_KEY` no longer exists.
- **Never in logs:** a canary key appears nowhere outside the Anthropic client. That covers the logs at DEBUG, the `run_events` payloads, the API responses and the stored rows.

The proof chosen for this phase is unit tests, Testcontainers tests and a dedicated no-leak test, all automated. No manual demo and no Playwright test were chosen.

## Automated checks
- [x] `packages/secrets/tests/` (no database):
  - [x] `test_round_trip`: encrypt, then decrypt, returns the same `SecretStr`.
  - [x] `test_tampered_ciphertext_fails`, `test_wrong_aad_fails`, `test_wrong_master_key_fails`: each raises `SecretDecryptError`, and the message doesn't contain the plaintext.
  - [x] `test_key_file_checks`: a missing file, or one that is not 32 bytes, raises `SecretsConfigError`.
  - [x] `test_generate_key_never_overwrites`.
  - [x] `test_redacting_filter`: a registered secret is replaced in `msg`, `%`-args and the exception traceback. It is no longer replaced after unregistering.
- [x] `packages/store/tests/test_connections.py` (Testcontainers Postgres):
  - [x] `put_connection` creates the workspace DEK once. A second put replaces the row, and the DEK stays the same.
  - [x] `list_connections` returns the hint and timestamps, and no ciphertext.
  - [x] `load_secret` returns the key. A row whose ciphertext was copied to another workspace fails to decrypt.
  - [x] `delete_connection`, then `load_secret` returns `None`.
- [x] `packages/api/tests/test_migrations.py`: upgrade to 0007 with an existing run, which is backfilled to the default workspace. Then downgrade and upgrade again.
- [x] `packages/api/tests/test_workspaces.py`:
  - [x] `GET /workspaces` lists the default workspace.
  - [x] `PUT` then `GET .../connections` shows `key_hint` only. The response body doesn't contain the key.
  - [x] An invalid `PUT` body gives a 422 that doesn't echo the key.
  - [x] Without `MASTER_KEY_FILE`, `PUT` returns 503, and `POST /runs` on the fake runtime still works.
  - [x] An unknown workspace returns 404 on the connection routes and on `POST /runs`.
- [x] `packages/worker/tests/test_build_runtime.py` and `test_worker.py`:
  - [x] The Claude factory builds the client with the stored key (a fake client class captures `api_key`). Two workspaces use two keys.
  - [x] A missing connection gives `run_failed` with "workspace has no Claude connection" after one attempt.
  - [x] The client is closed and the secret unregistered after the run completes, fails or is resumed.
  - [x] `AGENTIC_RUNTIME=claude` without a master key is a `ConfigError` at startup.
- [x] `packages/worker/tests/test_no_secret_leak.py`:
  - Store `sk-ant-canary-<uuid>` through the API.
  - Run a one-node workflow on the Claude factory with a fake client that emits text and usage. The fake client also raises an error that contains its `api_key`, so a leak through exception text is tested too.
  - Assert the canary (and its base64 and hex forms) appears in none of these:
    - [x] the captured log output (root logger at DEBUG, JSON formatter);
    - [x] the `run_events` payloads of the run;
    - [x] the bodies of every API response in the test;
    - [x] the `connections` and `workspaces` rows.
- [x] `web`: Vitest tests for `claude-connection.tsx` (empty state, save, field cleared after save, hint shown, delete, 503 message, invalid key, API unreachable). `pnpm lint` and `pnpm typecheck` pass.
- [x] Added beyond the plan:
  - `test_worker.py::test_a_key_stored_under_another_master_key_fails_the_run_cleanly`.
  - The no-leak test was checked by mutation: with event redaction switched off, it fails.
  - The compose stack was brought up in an isolated project: `keygen` writes the master key once (a second run keeps it), a `PUT` stores a key, and the API logs don't contain it.
- [x] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` pass locally (CI runs on the PR).

## Manual / demo checks
- [ ] None required for merge. Before the MVP demo:
  - run `docker compose up --build`;
  - paste a real key on `/settings`;
  - start a one-node run with `AGENTIC_RUNTIME=claude`;
  - check that `docker compose logs | grep <key>` finds nothing.

## Merge criteria
- [ ] All checks above pass in CI (they pass locally).
- [x] `ANTHROPIC_API_KEY` is gone from code, compose and `.env.example` (`git grep ANTHROPIC_API_KEY` finds only CHANGELOG/README history notes).
- [x] `docker compose up` still works with no manual step (the `keygen` service creates the master key).
- [x] README "Secrets" section and CHANGELOG entry are written. `plan.md` is ticked.
- [ ] The roadmap phase is marked done in the implementing PR (`complete-phase`).
