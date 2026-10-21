import asyncio
import json
import logging
from collections.abc import Iterator

import pytest
from testcontainers.community.redis import RedisContainer

from agentic_engine.logging import JsonFormatter
from agentic_engine.worker import WorkerSettings, run


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"


@pytest.mark.integration
async def test_worker_starts_and_stops(redis_url: str, caplog: pytest.LogCaptureFixture) -> None:
    stop, ready = asyncio.Event(), asyncio.Event()
    caplog.set_level(logging.INFO, logger="agentic_engine.worker")

    task = asyncio.create_task(run(WorkerSettings(redis_url=redis_url), stop, ready))
    async with asyncio.timeout(10):
        await ready.wait()
    assert "worker ready" in caplog.messages

    stop.set()
    async with asyncio.timeout(5):
        await task

    assert caplog.messages[-1] == "worker stopping"


def test_json_formatter_emits_one_json_object() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)

    entry = json.loads(JsonFormatter().format(record))

    assert entry["msg"] == "hello world"
    assert entry["level"] == "info"
