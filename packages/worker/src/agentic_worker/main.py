"""Run worker process: takes run ids from the Redis queue and runs them, one at a time.

Each run's spec and input are read from Postgres and its events are written back there
(`PostgresEventSink`), where the API streams them. Agents run on the fake runtime unless
`AGENTIC_RUNTIME=claude`, which runs them on Claude with the key in `ANTHROPIC_API_KEY`.

A run with a `repo` gets a sandbox holding a clone of it for its whole duration, and its agents
get the repo tools that run in there. `SANDBOX_BACKEND` picks Docker containers or, where Docker
is unavailable, temp directories on this host (no isolation).
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import FrameType
from typing import Any, Literal
from uuid import UUID

import anthropic
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentic_engine.graph import record_unstarted_run, run_workflow
from agentic_engine.logging import configure_logging
from agentic_runtime import AgentRuntime, ClaudeRuntime, ToolExecutor
from agentic_runtime.claude import DEFAULT_MAX_TOKENS, DEFAULT_MAX_TURNS, DEFAULT_MODEL
from agentic_runtime.fake import FakeRuntime, slow_echo_script
from agentic_sandbox import FakeSandboxManager, SandboxError, SandboxManager, SandboxTools
from agentic_sandbox.docker_backend import DEFAULT_IMAGE
from agentic_store import PostgresEventSink, StoredRun, dequeue_run, get_run

log = logging.getLogger("agentic_worker")


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_by_name=True)

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
    # Read from the environment for now; encrypted per-workspace keys come in phase 1.4.
    anthropic_api_key: SecretStr | None = None
    claude_model: str = DEFAULT_MODEL
    claude_max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    claude_max_turns: int = Field(default=DEFAULT_MAX_TURNS, ge=1)
    # Where runs with a repo get their sandbox: Docker containers, or host temp dirs (no isolation).
    sandbox_backend: Literal["docker", "fake"] = "fake"
    sandbox_image: str = DEFAULT_IMAGE
    # The only directory runs may clone local repo paths from; unset allows https URLs only.
    sandbox_local_root: Path | None = None


type RuntimeFactory = Callable[[ToolExecutor | None], AgentRuntime]
"""Builds the runtime for one run, given its sandbox's tools (None for a run without a repo)."""


class ConfigError(RuntimeError):
    """The worker settings cannot start a runtime or a sandbox backend."""


def runtime_factory(settings: WorkerSettings) -> RuntimeFactory:
    """The runtimes this worker's runs use. Clients are made once and shared by every run."""
    if settings.runtime == "claude":
        if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value():
            raise ConfigError("AGENTIC_RUNTIME=claude needs ANTHROPIC_API_KEY to be set")
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        return lambda tools: ClaudeRuntime(
            client,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            max_turns=settings.claude_max_turns,
            tools=tools,
        )
    if settings.fake_step_delay_s > 0:
        delay = settings.fake_step_delay_s
        return lambda tools: FakeRuntime(
            default=lambda text: slow_echo_script(text, delay), tools=tools
        )
    return lambda tools: FakeRuntime(tools=tools)


def build_runtime(settings: WorkerSettings, tools: ToolExecutor | None = None) -> AgentRuntime:
    return runtime_factory(settings)(tools)


def build_sandboxes(settings: WorkerSettings) -> SandboxManager:
    if settings.sandbox_backend == "fake":
        return FakeSandboxManager(local_root=settings.sandbox_local_root)
    import docker
    from docker.errors import DockerException

    from agentic_sandbox.docker_backend import DockerSandboxManager, sweep_orphans

    try:
        client = docker.from_env()
        # Runs are not resumed after a restart yet (phase 1.3): any sandbox left is an orphan.
        if removed := sweep_orphans(client):
            log.info("removed %d leftover sandbox(es)", removed)
    except DockerException as e:
        raise ConfigError(f"SANDBOX_BACKEND=docker but Docker is not reachable: {e}") from e
    return DockerSandboxManager(
        client, image=settings.sandbox_image, local_root=settings.sandbox_local_root
    )


async def process_run(
    sessions: async_sessionmaker[AsyncSession],
    make_runtime: RuntimeFactory,
    sandboxes: SandboxManager,
    run_id: UUID,
) -> None:
    """Run one queued run to its end. An error is logged and the worker carries on with the next
    run; if the run had started, its `run_failed` event is already written."""
    try:
        run = await get_run(sessions, run_id)
        if run is None:
            log.warning("run %s not found; skipped", run_id)
            return
        if run.status != "queued":
            log.warning("run %s is %s, not queued; skipped", run_id, run.status)
            return
        log.info("run %s started", run_id)
        result = await _run(run, PostgresEventSink(sessions), make_runtime, sandboxes)
    except asyncio.CancelledError:
        log.info("run %s cancelled", run_id)
        raise
    except Exception:
        log.exception("run %s crashed", run_id)
        return
    log.info("run %s %s", run_id, result)


async def _run(
    run: StoredRun,
    sink: PostgresEventSink,
    make_runtime: RuntimeFactory,
    sandboxes: SandboxManager,
) -> str:
    """Run `run`, inside a sandbox holding its repo if it has one; returns its status. A sandbox
    that cannot be opened ends the run before its first node."""
    if run.repo is None:
        result = await run_workflow(
            run.spec, make_runtime(None), run.input, run_id=run.id, sink=sink
        )
        return result.status
    async with contextlib.AsyncExitStack() as stack:
        try:
            sandbox = await stack.enter_async_context(sandboxes.open(run.id, run.repo))
        except SandboxError as e:
            log.warning("run %s has no sandbox: %s", run.id, e)
            await _unstarted(run, sink, "failed", str(e))
            return "failed"
        except asyncio.CancelledError:
            await _unstarted(run, sink, "cancelled", "cancelled while preparing the sandbox")
            raise
        runtime = make_runtime(SandboxTools(sandbox))
        result = await run_workflow(run.spec, runtime, run.input, run_id=run.id, sink=sink)
        return result.status


async def _unstarted(
    run: StoredRun, sink: PostgresEventSink, status: Literal["failed", "cancelled"], reason: str
) -> None:
    await record_unstarted_run(
        run.spec, run.input, run_id=run.id, sink=sink, status=status, reason=reason
    )


async def run(
    settings: WorkerSettings,
    stop: asyncio.Event,
    ready: asyncio.Event | None = None,
    *,
    runtime: AgentRuntime | None = None,
    make_runtime: RuntimeFactory | None = None,
    sandboxes: SandboxManager | None = None,
) -> None:
    """Take runs off the queue until `stop` is set; a run still going then is cancelled.

    Tests pass `runtime` (used for every run, whatever its tools) or `make_runtime`, and
    `sandboxes`; otherwise they are built from `settings`."""
    if make_runtime is None:
        fixed = runtime
        make_runtime = (lambda _tools: fixed) if fixed else runtime_factory(settings)
    sandboxes = sandboxes or build_sandboxes(settings)
    redis = Redis.from_url(settings.redis_url)  # pyright: ignore[reportUnknownMemberType]
    db = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(db, expire_on_commit=False)
    try:
        await redis.ping()  # pyright: ignore[reportUnknownMemberType]
        log.info("worker ready")
        if settings.ready_file is not None:
            settings.ready_file.touch()
        if ready is not None:
            ready.set()
        while not stop.is_set():
            run_id = await dequeue_run(redis, settings.queue_poll_s)
            if run_id is not None:
                await _until_stopped(process_run(sessions, make_runtime, sandboxes, run_id), stop)
        log.info("worker stopping")
    finally:
        if settings.ready_file is not None:
            settings.ready_file.unlink(missing_ok=True)
        await redis.aclose()
        await db.dispose()


async def _until_stopped(work: Coroutine[Any, Any, None], stop: asyncio.Event) -> None:
    """Await `work`, cancelling it if `stop` is set first (the run then ends `run_cancelled`)."""
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
    asyncio.run(_main())


if __name__ == "__main__":
    main()
