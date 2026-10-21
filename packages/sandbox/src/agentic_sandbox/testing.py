"""Test helpers shared by the sandbox and worker test suites."""

import subprocess
from collections.abc import Mapping
from pathlib import Path

SAMPLE_FILES: Mapping[str, str] = {
    "README.md": "# Hello repo\n",
    "src/app.py": "print('hello')\n",
    "src/pkg/__init__.py": "",
    "src/pkg/deep/mod.py": "X = 1\n",
    "docs/guide.md": "Read me.\n",
}


def make_repo(path: Path, files: Mapping[str, str] = SAMPLE_FILES) -> Path:
    """A git repo at `path` with one commit holding `files`; returns `path`."""
    for name, text in files.items():
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-C", str(path)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return path
