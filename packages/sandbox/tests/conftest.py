from pathlib import Path

import pytest

from agentic_sandbox.testing import make_repo


@pytest.fixture
def repos(tmp_path: Path) -> Path:
    """The allowed local root; it holds the `hello` sample repo."""
    root = tmp_path / "repos"
    make_repo(root / "hello")
    return root
