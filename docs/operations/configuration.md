# Configuration reference

Every service is configured through environment variables (read by `pydantic-settings`; variable names are case-insensitive, and an empty value counts as unset). For local development, copy [`.env.example`](../../.env.example) to `.env`; [`docker-compose.yml`](../../docker-compose.yml) passes the values to each container. In production, inject them from your secret manager.

Files referenced below (master key, GitHub App key) should be mounted read-only from a secret store, never baked into an image.

## API (`agentic_api`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://agentic:agentic@localhost:5432/agentic` | Postgres connection (asyncpg driver). Use TLS in production (`?ssl=require`). |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for the run queue and GitHub install state. Use `rediss://` for TLS. |
| `READINESS_TIMEOUT_S` | `2.0` | Timeout of each dependency check in `GET /health/ready`. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of browser origins allowed to call the API: the web app's public URL. |
| `MASTER_KEY_FILE` | unset | Path to the 32-byte master key. **Required to store model keys.** Must be the same file as the worker's. |
| `GITHUB_APP_ID` | unset | Your GitHub App's numeric id. Unset: GitHub endpoints answer `503`, everything else works. |
| `GITHUB_APP_SLUG` | unset | The App's URL slug (`github.com/apps/<slug>`). |
| `GITHUB_APP_PRIVATE_KEY_FILE` | unset | Path to the App's private key (`.pem`). |
| `WEB_BASE_URL` | `http://localhost:3000` | Public URL of the web app; the GitHub install flow redirects the browser there. |
| `API_BASE_URL` | `http://localhost:8000` | Public URL of the API (used by the fake GitHub install flow). |
| `AGENTIC_ENV` | `development` | `production` refuses the fakes below. **Set it in every real deployment.** |
| `CLAUDE_KEY_CHECK` | `anthropic` | How a Claude key is verified before it is stored: one real call (`anthropic`) or by prefix `sk-ant-test-` (`fake`, tests only). |
| `AGENTIC_GITHUB` | `app` | `fake` replaces GitHub with local bare repos (dev and e2e only). |
| `FAKE_GITHUB_ROOT` | unset | Where the fake App keeps its bare repos. |

## Worker (`agentic_worker`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL`, `REDIS_URL` | as API | Same database and Redis as the API. |
| `MASTER_KEY_FILE` | unset | Same master key as the API; needed to decrypt workspace keys. |
| `AGENTIC_RUNTIME` | `fake` | Which provider runs `agent` nodes: `claude` for real runs, `fake` for scripted, offline runs. |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Default model for agents whose spec names none. |
| `CLAUDE_MAX_TOKENS` | `32000` | Output tokens per API call. |
| `CLAUDE_MAX_TURNS` | `50` | Tool-use turns per agent node. |
| `SANDBOX_BACKEND` | `fake` | ⚠️ `docker` for isolated containers. **`fake` uses temp directories on the worker host with no isolation**; never use it with real repositories. Compose sets `docker`. |
| `SANDBOX_IMAGE` | `agentic-dev/sandbox:dev` | Image built from [`packages/sandbox/Dockerfile`](../../packages/sandbox/Dockerfile). Push it to your registry and pin a digest in production. |
| `SANDBOX_LOCAL_ROOT` | unset | The only directory local repo paths may be cloned from. Unset: https URLs only (recommended in production). |
| `DOCKER_HOST` | Docker default | Standard Docker variable (read by docker-py): point the worker at a remote or rootless daemon. |
| `DOCKER_GID` | `0` | Compose only: group of the Docker socket on Linux (`stat -c %g /var/run/docker.sock`). |
| `WORKER_ID` | hostname + pid | Names the worker in run leases. Must be unique per process. |
| `LEASE_TTL_S` | `30` | A lease not renewed for this long is expired and its run reclaimed. |
| `LEASE_HEARTBEAT_S` | `10` | How often a live worker renews its lease. Keep well below `LEASE_TTL_S`. |
| `MAX_ATTEMPTS` | `3` | Claims of one run before it fails instead of being resumed again. |
| `QUEUE_POLL_S` | `1.0` | How long one queue poll blocks. |
| `CANCEL_POLL_S` | `1.0` | How often a running run is checked for a cancel request. |
| `GATE_SWEEP_S` | `30` | How often expired gates are swept. |
| `READY_FILE` | unset | File touched once the worker is ready (container health checks). |
| `FAKE_STEP_DELAY_S` | `0` | Pause between fake runtime events, so demo runs stream visibly. |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY_FILE` | unset | Same App as the API. Unset: GitHub repos are cloned anonymously and `github.*` tools fail. |
| `AGENTIC_GITHUB`, `AGENTIC_ENV` | `app`, `development` | As for the API. |

Sandbox resource limits (512 MB memory, 1 CPU, 256 PIDs per run) are set in `agentic_sandbox.docker_backend.SandboxLimits`.

## Web (`web/`)

| Variable | When | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | **Build time** (`--build-arg`) | `http://localhost:8000` | Where the browser reaches the API. Next.js inlines it into the bundle, so each environment builds its own image. |
| `PORT`, `HOSTNAME` | Run time | `3000`, `0.0.0.0` | Where the Node server listens. |

## Compose-only variables

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `agentic` | Credentials of the bundled Postgres. **Change the password** anywhere other than a laptop. |
| `API_PORT`, `WEB_PORT` | `8000`, `3000` | Host ports for the API and web app. |

## Platform policy

Run limits are not environment variables. The platform ceilings live in code (`agentic_engine.policy.PLATFORM_POLICY`); each workspace may lower them in **Settings → Limits and budgets** or with `PUT /workspaces/{id}/policy`. Model prices are set in **Settings → Models and pricing** or with `PUT /workspaces/{id}/pricing`.

## Generating secrets

```bash
# Master key (32 random bytes); keep a backup apart from the database.
uv run python -m agentic_secrets generate-key .secrets/master.key
```

With compose, the one-shot `keygen` service runs the same command (`--if-missing`) into the `secrets` volume on first start. In Kubernetes, generate the key once, store it as a secret (or in your KMS-backed secret store), and mount it read-only into the API and worker pods.
