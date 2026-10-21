from collections.abc import Iterator

import pytest

from agentic_runtime.testing import block_network


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Engine tests never reach the network; `integration` tests (Testcontainers) are exempt."""
    if "integration" in request.keywords:
        yield
        return
    with block_network():
        yield
