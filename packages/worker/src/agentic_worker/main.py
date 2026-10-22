"""Run worker process: takes runs one at a time and runs them, resuming those other workers lost.

The Redis queue announces new runs; Postgres decides who runs what. A worker claims a run's lease
before running it and renews it while alive (`agentic_store.lease`). Each node's outcome is
checkpointed in Postgres, so when a worker dies its run's lease expires and the next worker that
looks reclaims it and resumes it after its last completed node (AC-8). A stopping worker cancels
its run without ending it and releases the lease, so the run is resumed at once elsewhere.

A run that reaches a gate pauses: it becomes `waiting`, the worker releases it and moves on, and
the run's sandbox is kept. A decision (`POST /runs/{id}/approvals`) queues it again, and the
worker that claims it opens the kept sandbox and continues the run with the decision.

Each run's spec and input are read from Postgres and its events are written back there
(`PostgresEventSink`), where the API streams them. Agents run on the fake runtime unless
`AGENTIC_RUNTIME=claude`, which runs them on Claude with the Claude key stored (encrypted) in the
run's workspace. The key is decrypted when the run starts, used only by that run's Anthropic
client, and redacted from logs and events while it is held. A workspace with no stored key
fails its runs on Claude.

A run with a `repo` gets a sandbox holding a clone of it for its whole duration, and its agents
and tool nodes get the `repo.*` tools: a read-only `repo` MCP server bound to that sandbox,
connected in memory. Each writer node (one whose spec names `repo.write_file` or `repo.commit`)
gets its own worktree on `agent/<run>/<node>` instead, with the write tools.

A run whose repo is on GitHub, in a workspace linked to the platform's GitHub App, is cloned with
an installation token (so private repos work); the token reaches git through its environment and
is redacted from logs meanwhile. If its spec uses `github.*` tools, it also gets the `github` MCP
server: `github.openPR` bundles a writer's branch out of the sandbox, pushes it from this worker
and opens a pull request. The sandbox never holds a credential and has no network.
`SANDBOX_BACKEND` picks Docker containers or, where Docker is unavailable, temp directories on
this host (no isolation).

A user can cancel a run (`POST /runs/{id}/cancel`): the worker running it checks every
`CANCEL_POLL_S`, cancels its graph and writes `run_cancelled`; a cancelled run that is claimed
(queued, or paused at a gate) is ended at once, and a sandbox it kept is removed.
"""

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
from collections.abc import AsyncGenerator, Callable, Collection, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Literal
from uuid import UUID

import anthropic
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentic_engine.events import RUN_CANCELLED, RUN_FAILED, EventSink, RunEvent, RunEventLog
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    Checkpointer,
    WorkflowRunResult,
    record_unstarted_run,
    resume_workflow,
    run_workflow,
)
from agentic_engine.logging import configure_logging
from agentic_engine.spec import WorkflowSpec, iter_nodes, node_tools, writer_node_ids
from agentic_github import (
    GithubApiError,
    GithubApp,
    GithubAppConfig,
    GithubConfigError,
    InstallationNotFoundError,
    auth_env,
    repo_full_name,
)
from agentic_runtime import AgentRuntime, ClaudeRuntime, ToolExecutor
from agentic_runtime.claude import DEFAULT_MAX_TOKENS, DEFAULT_MAX_TURNS, DEFAULT_MODEL
from agentic_runtime.fake import FakeRuntime, slow_echo_script
from agentic_sandbox import FakeSandboxManager, SandboxError, SandboxManager
from agentic_sandbox.docker_backend import DEFAULT_IMAGE
from agentic_secrets import (
    KeyProvider,
    LocalKeyProvider,
    SecretDecryptError,
    SecretsConfigError,
    install_redaction,
    redact_json,
    registered,
)
from agentic_store import (
    USER_CANCEL_REASON,
    PostgresEventSink,
    StoredRun,
    cancel_requested,
    claim_run,
    dequeue_run,
    get_github_installation,
    leased_run_ids,
    load_secret,
    max_event_seq,
    open_checkpointer,
    pending_decision,
    reclaim_expired_run,
    release_run,
    renew_lease,
    run_ended,
    waiting_run_ids,
)
from agentic_tools.github import GithubPublisher, GithubTarget, open_github_tools
from agentic_tools.repo import WRITE_TOOL_NAMES, open_repo_tools
from agentic_tools.routing import RunTools

log = logging.getLogger("agentic_worker")


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class WorkerSettings(BaseSettings):
    # An empty variable (compose passes `${X:-}`) means unset.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", validate_by_name=True, env_ignore_empty=True
    )

    database_url: str = "postgresql+asyncpg://agentic:agentic@localhost:5432/agentic"
    redis_url: str = "redis://localhost:6379/0"
    # Touched once Redis answers; container healthchecks test for it.
    ready_file: Path | None = None
    # How long one queue poll blocks; bounds how quickly an idle worker sees `stop`.
    queue_poll_s: float = 1.0
    # Pause before each fake runtime event, so a run streams visibly (0 = instant).
    fake_step_delay_s: float = 0.0
    # Which provider runs agent nodes (env `AGENTIC_RUNTIME`).
    runtime: Literal["fake", "claude"] = Field(default="fake", validation_alias="agentic_runtime")
    # The master key that decrypts workspaces' stored keys (a 32-byte file, shared with the API).
    master_key_file: Path | None = None
    claude_model: str = DEFAULT_MODEL
    claude_max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    claude_max_turns: int = Field(default=DEFAULT_MAX_TURNS, ge=1)
    # Where runs with a repo get their sandbox: Docker containers, or host temp dirs (no isolation).
    sandbox_backend: Literal["docker", "fake"] = "fake"
    sandbox_image: str = DEFAULT_IMAGE
    # The only directory runs may clone local repo paths from; unset allows https URLs only.
    sandbox_local_root: Path | None = None
    # Names this worker in run leases.
    worker_id: str = Field(default_factory=_default_worker_id, min_length=1, max_length=128)
    # A lease not renewed for this long is expired, and its run is reclaimed by another worker.
    lease_ttl_s: float = Field(default=30.0, gt=0)
    lease_heartbeat_s: float = Field(default=10.0, gt=0)
    # How often a running run is checked for a user's cancel request.
    cancel_poll_s: float = Field(default=1.0, gt=0)
    # Claims of one run before it fails instead of being resumed again (a run that kills workers).
    max_attempts: int = Field(default=3, ge=1)
    # The platform's GitHub App (the same settings as the API's). Unset, runs clone GitHub repos
    # anonymously and runs that use `github.*` tools fail.
    github_app_id: int | None = None
    github_app_slug: str | None = None
    github_app_private_key_file: Path | None = None


type RuntimeFactory = Callable[[ToolExecutor | None], AgentRuntime]
"""Builds the runtime for one run, given its sandbox's tools (None for a run without a repo)."""

type RunRuntimes = Callable[
    [StoredRun, ToolExecutor | None], AbstractAsyncContextManager[AgentRuntime]
]
"""Opens the runtime for one run, given the run and its sandbox's tools, for as long as the run
lasts; closing it releases what the run held (its provider client and decrypted key)."""

type ClaudeClientFactory = Callable[[SecretStr], anthropic.AsyncAnthropic]


class ConfigError(RuntimeError):
    """The worker settings cannot start a runtime or a sandbox backend."""


class RunSetupError(RuntimeError):
    """A run cannot start on this worker, e.g. its workspace has no key for its provider. The
    run fails with this message, which is safe to show (it never holds a secret)."""


def anthropic_client(key: SecretStr) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=key.get_secret_value())


def build_keys(settings: WorkerSettings) -> KeyProvider | None:
    """The master key provider, if `MASTER_KEY_FILE` is set."""
    if settings.master_key_file is None:
        return None
    try:
        return LocalKeyProvider.from_file(settings.master_key_file)
    except SecretsConfigError as e:
        raise ConfigError(str(e)) from None


def fake_runtime_factory(settings: WorkerSettings) -> RuntimeFactory:
    if settings.fake_step_delay_s > 0:
        delay = settings.fake_step_delay_s
        return lambda tools: FakeRuntime(
            default=lambda text: slow_echo_script(text, delay), tools=tools
        )
    return lambda tools: FakeRuntime(tools=tools)


def fixed_runtimes(make_runtime: RuntimeFactory) -> RunRuntimes:
    """Runtimes that hold nothing per run (the fake one, or one given by a test)."""

    @asynccontextmanager
    async def open_runtime(
        _run: StoredRun, tools: ToolExecutor | None
    ) -> AsyncGenerator[AgentRuntime]:
        yield make_runtime(tools)

    return open_runtime


def run_runtimes(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider | None,
    make_client: ClaudeClientFactory = anthropic_client,
) -> RunRuntimes:
    """The runtimes this worker's runs use. On Claude, each run gets its own client, made with
    its workspace's key and closed when the run's attempt ends."""
    if settings.runtime != "claude":
        return fixed_runtimes(fake_runtime_factory(settings))
    if keys is None:
        raise ConfigError("AGENTIC_RUNTIME=claude needs MASTER_KEY_FILE to read stored keys")
    master = keys

    async def claude_key(run: StoredRun) -> SecretStr:
        try:
            stored = await load_secret(sessions, master, run.workspace_id, "claude")
        except SecretDecryptError:
            raise RunSetupError(
                "the workspace's Claude key cannot be decrypted; store it again"
            ) from None
        if stored is None:
            raise RunSetupError("workspace has no Claude connection")
        return stored

    @asynccontextmanager
    async def open_claude(
        run: StoredRun, tools: ToolExecutor | None
    ) -> AsyncGenerator[AgentRuntime]:
        key = await claude_key(run)
        with registered(key):
            client = make_client(key)
            try:
                yield ClaudeRuntime(
                    client,
                    model=settings.claude_model,
                    max_tokens=settings.claude_max_tokens,
                    max_turns=settings.claude_max_turns,
                    tools=tools,
                )
            finally:
                await client.close()

    return open_claude


def build_github(settings: WorkerSettings) -> GithubApp | None:
    """The platform's GitHub App, if its id and slug are set."""
    if settings.github_app_id is None or settings.github_app_slug is None:
        return None
    if settings.github_app_private_key_file is None:
        raise ConfigError("GITHUB_APP_PRIVATE_KEY_FILE must be set with GITHUB_APP_ID")
    try:
        config = GithubAppConfig.from_file(
            settings.github_app_id, settings.github_app_slug, settings.github_app_private_key_file
        )
    except GithubConfigError as e:
        raise ConfigError(str(e)) from None
    return GithubApp(config)


def build_sandboxes(
    settings: WorkerSettings, keep: Collection[str] = frozenset()
) -> SandboxManager:
    """The sandbox backend. For Docker, leftover sandboxes are removed first, except those of the
    run ids in `keep` (runs other workers are running, and runs paused at a gate)."""
    if settings.sandbox_backend == "fake":
        return FakeSandboxManager(local_root=settings.sandbox_local_root)
    import docker
    from docker.errors import DockerException

    from agentic_sandbox.docker_backend import DockerSandboxManager, sweep_orphans

    try:
        client = docker.from_env()
        if removed := sweep_orphans(client, keep):
            log.info("removed %d leftover sandbox(es)", removed)
    except DockerException as e:
        raise ConfigError(f"SANDBOX_BACKEND=docker but Docker is not reachable: {e}") from e
    return DockerSandboxManager(
        client, image=settings.sandbox_image, local_root=settings.sandbox_local_root
    )


@dataclass(frozen=True)
class Worker:
    """What a worker runs its runs with."""

    settings: WorkerSettings
    sessions: async_sessionmaker[AsyncSession]
    open_runtime: RunRuntimes
    sandboxes: SandboxManager
    checkpointer: Checkpointer
    github: GithubPublisher | None = None
    # Where a repo's branches are pushed, by `owner/name`; GitHub unless a test points elsewhere.
    github_remote: Callable[[str], str] | None = None


class AttemptSink:
    """Writes one attempt's events until the worker lets the run go (it is stopping, or another
    worker took the lease). Later events are dropped, so a cancelled attempt does not end the run
    and it stays resumable. Live secrets are redacted from payloads before they are written."""

    def __init__(self, sink: EventSink, detached: Callable[[], bool]) -> None:
        self._sink = sink
        self._detached = detached

    async def emit(self, event: RunEvent) -> None:
        if not self._detached():
            payload = redact_json(event.payload)
            if payload != event.payload:
                event = event.model_copy(update={"payload": payload})
            await self._sink.emit(event)


async def process_run(worker: Worker, run: StoredRun, stop: asyncio.Event) -> None:
    """Run a claimed run to its end, renewing its lease meanwhile, then release it. An error is
    logged and the worker carries on with the next run; if the run had started, its `run_failed`
    event is already written. If the lease is lost, the run is left to the worker that has it."""
    lost = asyncio.Event()
    sink = AttemptSink(PostgresEventSink(worker.sessions), lambda: stop.is_set() or lost.is_set())
    if await cancel_requested(worker.sessions, run.id):
        try:
            await _end_cancelled(worker, run, sink)
            log.info("run %s cancelled before it ran", run.id)
        finally:
            await release_run(worker.sessions, run.id, worker.settings.worker_id)
        return
    attempt = asyncio.create_task(_attempt(worker, run, sink))
    heartbeat = asyncio.create_task(_keep_lease(worker, run.id, lost))
    cancel = asyncio.create_task(_watch_cancel(worker, run.id))
    try:
        await asyncio.wait({attempt, heartbeat, cancel}, return_when=asyncio.FIRST_COMPLETED)
        if cancel.done() and not attempt.done():
            # The sink stays attached, so the graph writes `node_cancelled` and `run_cancelled`.
            attempt.cancel(USER_CANCEL_REASON)
            with contextlib.suppress(asyncio.CancelledError):
                await attempt
            await _end_cancelled(worker, run, sink)
            log.info("run %s cancelled by its user", run.id)
            return
        if not attempt.done():
            log.warning("run %s: lease lost to another worker; dropped", run.id)
            return
        log.info("run %s %s", run.id, attempt.result())
    except asyncio.CancelledError:
        log.info("run %s released for another worker to resume", run.id)
        raise
    except Exception:
        log.exception("run %s crashed", run.id)
    finally:
        heartbeat.cancel()
        cancel.cancel()
        if not attempt.done():
            attempt.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await attempt
        await release_run(worker.sessions, run.id, worker.settings.worker_id)


async def _keep_lease(worker: Worker, run_id: UUID, lost: asyncio.Event) -> None:
    """Renew the run's lease every `lease_heartbeat_s`; returns once it has been lost."""
    settings = worker.settings
    while True:
        await asyncio.sleep(settings.lease_heartbeat_s)
        try:
            held = await renew_lease(
                worker.sessions, run_id, settings.worker_id, settings.lease_ttl_s
            )
        except Exception:
            log.warning("run %s: could not renew its lease", run_id, exc_info=True)
            continue
        if not held:
            lost.set()
            return


async def _watch_cancel(worker: Worker, run_id: UUID) -> None:
    """Return once a user has asked to cancel the run, checking every `cancel_poll_s`."""
    while True:
        await asyncio.sleep(worker.settings.cancel_poll_s)
        try:
            if await cancel_requested(worker.sessions, run_id):
                return
        except Exception:
            log.warning("run %s: could not check for a cancel request", run_id, exc_info=True)


async def _end_cancelled(worker: Worker, run: StoredRun, sink: EventSink) -> None:
    """End a run its user cancelled, unless its graph already wrote its end: `run_cancelled`
    after its last event (a run that never started gets `run_started` first). A sandbox the run
    kept at a gate is removed."""
    if not await run_ended(worker.sessions, run.id):
        last_seq = await max_event_seq(worker.sessions, run.id)
        if last_seq == 0:
            await record_unstarted_run(
                run.spec,
                run.input,
                run_id=run.id,
                sink=sink,
                status="cancelled",
                reason=USER_CANCEL_REASON,
            )
        else:
            await RunEventLog(run.id, sink, next_seq=last_seq + 1).emit(
                RUN_CANCELLED, payload={"reason": USER_CANCEL_REASON}
            )
    if run.repo is not None:
        await worker.sandboxes.discard(run.id)


async def _attempt(worker: Worker, run: StoredRun, sink: EventSink) -> str:
    """Start `run`, or resume it if an earlier attempt wrote events; returns its status. A run
    with a repo runs inside a sandbox holding it; one that cannot be opened ends the run.

    A run continued after a gate decision opens the sandbox it kept when it paused, so its
    writers' commits are still there; a run that pauses at a gate keeps its sandbox."""
    last_seq = await max_event_seq(worker.sessions, run.id)
    decision = await pending_decision(worker.sessions, run.id) if last_seq else None
    tries = run.attempt - 1
    if tries >= worker.settings.max_attempts:
        log.warning("run %s: gave up after %d attempts", run.id, tries)
        await _fail(run, sink, last_seq, f"gave up after {tries} attempts")
        return "failed"
    try:
        target = await _github_target(worker, run)
    except RunSetupError as e:
        log.warning("run %s cannot start: %s", run.id, e)
        await _fail(run, sink, last_seq, str(e))
        return "failed"
    async with contextlib.AsyncExitStack() as stack:
        tools: ToolExecutor | None = None
        if run.repo is not None:
            token = await _clone_token(worker, run.id, target)
            try:
                with registered(token) if token is not None else contextlib.nullcontext():
                    sandbox = await stack.enter_async_context(
                        worker.sandboxes.open(
                            run.id,
                            run.repo,
                            reuse=decision is not None,
                            git_env=auth_env(token) if token is not None else None,
                        )
                    )
            except SandboxError as e:
                log.warning("run %s has no sandbox: %s", run.id, e)
                await _fail(run, sink, last_seq, str(e))
                return "failed"
            # Entered after the sandbox, so the MCP clients close before the sandbox is destroyed.
            writers = writer_node_ids(run.spec.root, WRITE_TOOL_NAMES)
            tools = await stack.enter_async_context(
                open_repo_tools(sandbox, run_id=run.id, writers=writers)
            )
            if target is not None and uses_github(run.spec):
                assert worker.github is not None  # `_github_target` checked it
                publishing = await stack.enter_async_context(
                    open_github_tools(
                        worker.github, target, sandbox, run_id=run.id, writers=writers
                    )
                )
                tools = RunTools([tools, publishing])
        try:
            runtime = await stack.enter_async_context(worker.open_runtime(run, tools))
        except RunSetupError as e:
            log.warning("run %s cannot start: %s", run.id, e)
            await _fail(run, sink, last_seq, str(e))
            return "failed"
        result = await _workflow(worker, run, sink, last_seq, runtime, tools, decision)
        if result.status == "waiting" and run.repo is not None:
            worker.sandboxes.keep(run.id)
        return result.status


def uses_github(spec: WorkflowSpec) -> bool:
    """Whether a node of `spec` names a `github.*` tool."""
    return any(
        tool.startswith("github.") for _, node in iter_nodes(spec.root) for tool in node_tools(node)
    )


async def _github_target(worker: Worker, run: StoredRun) -> GithubTarget | None:
    """Where the run's repo is on GitHub and through which installation, if it is on GitHub and
    its workspace is linked to the platform's GitHub App. Raises `RunSetupError` if the run uses
    `github.*` tools and has no such target."""
    needed = uses_github(run.spec)
    full_name = repo_full_name(run.repo.url) if run.repo is not None else None
    if full_name is None or worker.github is None:
        if needed and worker.github is None:
            raise RunSetupError("the GitHub App is not configured on this worker")
        if needed:
            raise RunSetupError("the run's repo is not on GitHub")
        return None
    installation = await get_github_installation(worker.sessions, run.workspace_id)
    if installation is None:
        if needed:
            raise RunSetupError("workspace has no GitHub connection")
        return None
    assert run.repo is not None
    return GithubTarget(
        installation_id=installation,
        full_name=full_name,
        base=run.repo.ref,
        remote_url=worker.github_remote(full_name) if worker.github_remote else None,
    )


async def _clone_token(
    worker: Worker, run_id: UUID, target: GithubTarget | None
) -> SecretStr | None:
    """An installation token to clone the run's repo with (private repos need one), or `None`
    to clone anonymously: the repo is not on GitHub, or no token could be had (the clone then
    works for public repos only)."""
    if target is None or worker.github is None:
        return None
    try:
        return await worker.github.installation_token(target.installation_id)
    except (GithubApiError, InstallationNotFoundError) as e:
        log.warning("run %s: no GitHub token for the clone (%s); cloning anonymously", run_id, e)
        return None


async def _workflow(
    worker: Worker,
    run: StoredRun,
    sink: EventSink,
    last_seq: int,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    decision: GateDecision | None = None,
) -> WorkflowRunResult:
    """Start or resume the run's graph. Tool nodes call `tools`, the executor agents use too. A
    run paused at a gate continues with `decision`."""
    if last_seq == 0:
        log.info("run %s started", run.id)
        return await run_workflow(
            run.spec,
            runtime,
            run.input,
            run_id=run.id,
            sink=sink,
            checkpointer=worker.checkpointer,
            tools=tools,
        )
    log.info("run %s resumed (attempt %d)", run.id, run.attempt)
    return await resume_workflow(
        run.spec,
        runtime,
        run.input,
        run_id=run.id,
        sink=sink,
        checkpointer=worker.checkpointer,
        next_seq=last_seq + 1,
        attempt=run.attempt,
        tools=tools,
        decision=decision,
    )


async def _fail(run: StoredRun, sink: EventSink, last_seq: int, error: str) -> None:
    """End the run as failed before (re)starting its graph: a fresh run gets `run_started`
    first, a resumed one just `run_failed` after its last event."""
    if last_seq == 0:
        await record_unstarted_run(
            run.spec, run.input, run_id=run.id, sink=sink, status="failed", reason=error
        )
    else:
        await RunEventLog(run.id, sink, next_seq=last_seq + 1).emit(
            RUN_FAILED, payload={"error": error}
        )


async def _next_run(worker: Worker, redis: Redis) -> StoredRun | None:
    """An abandoned run to resume if there is one, else a new run from the queue (waiting up to
    `queue_poll_s`); `None` if there is neither."""
    settings = worker.settings
    run = await reclaim_expired_run(worker.sessions, settings.worker_id, settings.lease_ttl_s)
    if run is not None:
        log.info("run %s reclaimed (attempt %d)", run.id, run.attempt)
        return run
    run_id = await dequeue_run(redis, settings.queue_poll_s)
    if run_id is None:
        return None
    run = await claim_run(worker.sessions, run_id, settings.worker_id, settings.lease_ttl_s)
    if run is None:
        log.warning("run %s is not a queued run free to claim; skipped", run_id)
    return run


async def run(
    settings: WorkerSettings,
    stop: asyncio.Event,
    ready: asyncio.Event | None = None,
    *,
    runtime: AgentRuntime | None = None,
    make_runtime: RuntimeFactory | None = None,
    make_client: ClaudeClientFactory | None = None,
    sandboxes: SandboxManager | None = None,
    checkpointer: Checkpointer | None = None,
    github: GithubPublisher | None = None,
    github_remote: Callable[[str], str] | None = None,
) -> None:
    """Run abandoned and queued runs until `stop` is set; a run still going then is released
    unfinished, for another worker to resume.

    Tests pass `runtime` (used for every run, whatever its tools) or `make_runtime`, or
    `make_client` for the Claude runtime, and `sandboxes`, `checkpointer` and `github` (with
    `github_remote`, where branches are pushed); otherwise they are built from `settings`."""
    keys = build_keys(settings)
    app = build_github(settings) if github is None else None
    redis = Redis.from_url(settings.redis_url)  # pyright: ignore[reportUnknownMemberType]
    db = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(db, expire_on_commit=False)
    try:
        if runtime is not None:
            fixed = runtime
            open_runtime = fixed_runtimes(lambda _tools: fixed)
        elif make_runtime is not None:
            open_runtime = fixed_runtimes(make_runtime)
        else:
            open_runtime = run_runtimes(settings, sessions, keys, make_client or anthropic_client)
        async with contextlib.AsyncExitStack() as stack:
            if sandboxes is None:
                keep = await leased_run_ids(sessions) | await waiting_run_ids(sessions)
                sandboxes = build_sandboxes(settings, keep={str(i) for i in keep})
            if checkpointer is None:
                checkpointer = await stack.enter_async_context(
                    open_checkpointer(settings.database_url)
                )
            if app is not None:
                stack.callback(app.close)
            worker = Worker(
                settings,
                sessions,
                open_runtime,
                sandboxes,
                checkpointer,
                github=github or app,
                github_remote=github_remote,
            )
            await redis.ping()  # pyright: ignore[reportUnknownMemberType]
            log.info("worker ready")
            if settings.ready_file is not None:
                settings.ready_file.touch()
            if ready is not None:
                ready.set()
            while not stop.is_set():
                run = await _next_run(worker, redis)
                if run is not None:
                    await _until_stopped(process_run(worker, run, stop), stop)
            log.info("worker stopping")
    finally:
        if settings.ready_file is not None:
            settings.ready_file.unlink(missing_ok=True)
        await redis.aclose()
        await db.dispose()


async def _until_stopped(work: Coroutine[Any, Any, None], stop: asyncio.Event) -> None:
    """Await `work`, cancelling it if `stop` is set first (its run is released, not ended)."""
    task = asyncio.create_task(work)
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, on_signal)
    await run(WorkerSettings(), stop)


def main() -> None:
    configure_logging()
    install_redaction()
    # psycopg (the checkpointer's driver) cannot use Windows' default Proactor loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
