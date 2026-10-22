"""`push_bundle` against a local bare repo standing in for GitHub (a `file://` remote)."""

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr

from agentic_github import PushError, auth_env, github_remote, push_bundle, repo_full_name

BRANCH = "agent/run-1/writer"
TOKEN = SecretStr("ghs_pushtoken0003")
_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *_ID, *args], cwd=cwd, env=_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


class Remote:
    """A bare repo with two commits on `main`, and a shallow clone of it, as a sandbox has."""

    def __init__(self, root: Path) -> None:
        source = root / "source"
        source.mkdir()
        git(source, "init", "-q", "-b", "main")
        (source / "README.md").write_text("hello\n")
        git(source, "add", "-A")
        git(source, "commit", "-q", "-m", "one")
        (source / "README.md").write_text("hello again\n")
        git(source, "commit", "-q", "-am", "two")
        self.bare = root / "remote.git"
        git(root, "clone", "-q", "--bare", str(source), str(self.bare))
        self.url = self.bare.resolve().as_uri()
        self.clone = root / "clone"
        git(root, "clone", "-q", "--depth", "1", "--no-local", self.url, str(self.clone))
        self.base = git(self.clone, "rev-parse", "HEAD")
        self._root = root

    def bundle(self, branch: str = BRANCH, *, files: dict[str, str] | None = None) -> bytes:
        """Commit `files` on a new `branch` of the clone, and bundle `base..branch`."""
        git(self.clone, "switch", "-q", "-C", branch, self.base)
        for name, text in (files or {"NOTES.md": "notes\n"}).items():
            (self.clone / name).write_text(text)
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "agent work")
        path = self._root / f"{branch.replace('/', '_')}.bundle"
        git(self.clone, "bundle", "create", "-q", str(path), f"{self.base}..{branch}")
        git(self.clone, "switch", "-q", "--detach", self.base)
        return path.read_bytes()

    def head(self, branch: str) -> str:
        return git(self.bare, "rev-parse", f"refs/heads/{branch}")


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    return Remote(tmp_path)


async def _push(remote: Remote, bundle: bytes, **overrides: object) -> str:
    args: dict[str, object] = {
        "remote_url": remote.url,
        "base_sha": remote.base,
        "branch": BRANCH,
        "token": None,
    }
    args.update(overrides)
    return await push_bundle(bundle, **args)  # type: ignore[arg-type]


async def test_push_creates_the_branch(remote: Remote) -> None:
    head = await _push(remote, remote.bundle())

    assert remote.head(BRANCH) == head
    assert git(remote.bare, "show", f"{head}:NOTES.md") == "notes"


async def test_push_works_after_the_base_branch_moved(remote: Remote, tmp_path: Path) -> None:
    bundle = remote.bundle()
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", remote.url, str(other))
    (other / "LATER.md").write_text("later\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "three")
    git(other, "push", "-q", "origin", "main")

    head = await _push(remote, bundle)

    assert remote.head(BRANCH) == head


async def test_pushing_the_same_commit_again_is_fine(remote: Remote) -> None:
    bundle = remote.bundle()
    first = await _push(remote, bundle)

    assert await _push(remote, bundle) == first


async def test_push_never_overwrites_an_existing_branch(remote: Remote) -> None:
    first = await _push(remote, remote.bundle())
    rewritten = remote.bundle(files={"OTHER.md": "x\n"})

    with pytest.raises(PushError, match="already exists"):
        await _push(remote, rewritten)

    assert remote.head(BRANCH) == first


async def test_push_refuses_a_bundle_not_built_on_the_base(remote: Remote) -> None:
    bundle = remote.bundle()
    first = git(remote.bare, "rev-list", "--max-parents=0", "main")

    with pytest.raises(PushError):
        await _push(remote, bundle, base_sha=first)

    assert git(remote.bare, "branch", "--list", BRANCH) == ""


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"base_sha": "main"}, "full commit id"),
        ({"branch": "--upload-pack=x"}, "not a branch"),
        ({"branch": "agent/../main"}, "not a branch"),
        ({"remote_url": "ssh://github.com/acme/api.git"}, "only https"),
    ],
)
async def test_push_refuses_bad_arguments(
    remote: Remote, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(PushError, match=message):
        await _push(remote, b"", **overrides)


async def test_push_errors_name_no_token_or_temp_path(remote: Remote) -> None:
    missing = remote.url.replace("remote.git", "missing.git")

    with pytest.raises(PushError) as caught:
        await _push(remote, remote.bundle(), remote_url=missing, token=TOKEN)

    message = str(caught.value)
    assert message.startswith("git fetch failed")
    assert TOKEN.get_secret_value() not in message
    assert "agentic-push-" not in message


def test_auth_env_sends_the_token_as_a_header_only() -> None:
    env = auth_env(TOKEN)

    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert TOKEN.get_secret_value() not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded


@pytest.mark.parametrize(
    ("url", "full_name"),
    [
        ("https://github.com/acme/api", "acme/api"),
        ("https://github.com/acme/api.git", "acme/api"),
        ("https://github.com/acme/my.repo/", "acme/my.repo"),
        ("https://gitlab.com/acme/api", None),
        ("https://github.com/acme", None),
        ("https://github.com/acme/api/tree/main", None),
        ("https://user@github.com/acme/api", None),
        ("http://github.com/acme/api", None),
        ("/repos/acme/api", None),
    ],
)
def test_repo_full_name(url: str, full_name: str | None) -> None:
    assert repo_full_name(url) == full_name


def test_github_remote() -> None:
    assert github_remote("acme/api") == "https://github.com/acme/api.git"
