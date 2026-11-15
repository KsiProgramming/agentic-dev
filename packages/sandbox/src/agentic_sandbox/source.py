"""Where a run's repo comes from, and the shallow clone the worker makes of it.

The clone runs on the worker, not in the sandbox, so the sandbox needs no network and never sees
credentials. Only two kinds of source are accepted: an `https://` URL without credentials, and a
local path under a root the worker allows (none by default).
"""

import asyncio
import contextlib
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_sandbox.errors import SandboxError

CLONE_TIMEOUT_S = 120.0

# `scheme://`, `transport::address` (e.g. git's `ext::` runs commands) and scp-like `user@host:`.
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_TRANSPORT = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*::")
_SCP_LIKE = re.compile(r"^[^/\\]+@[^/\\]+:")

# Must not start with `-` (read as an option); `..` is refused in the validator.
GitRef = Annotated[str, Field(pattern=r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$", max_length=200)]


class RepoSource(BaseModel):
    """The repo a run works on: an `https://` URL or a local path, at `ref` (default branch if
    unset)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: Annotated[str, Field(min_length=1, max_length=2000)]
    ref: GitRef | None = None

    @model_validator(mode="after")
    def _supported(self) -> Self:
        if self.ref is not None and ".." in self.ref:
            raise ValueError("repo ref must not contain '..'")
        url = self.url
        if url.startswith("-"):
            raise ValueError("repo url must not start with '-'")
        if scheme := _SCHEME.match(url):
            if scheme.group(1).lower() != "https":
                raise ValueError("repo url must be https:// or a local path")
            authority = url[len(scheme.group(0)) :].split("/", 1)[0]
            if "@" in authority:
                raise ValueError("repo url must not hold credentials")
        elif _TRANSPORT.match(url) or _SCP_LIKE.match(url):
            raise ValueError("repo url must be https:// or a local path")
        return self

    @property
    def is_local(self) -> bool:
        return _SCHEME.match(self.url) is None


def _local_repo(source: RepoSource, local_root: Path | None) -> str:
    """The resolved local path to clone, if it is under `local_root`."""
    if local_root is None:
        raise SandboxError("local repo paths are not allowed on this worker")
    path = Path(source.url).resolve()
    if not path.is_relative_to(local_root.resolve()):
        raise SandboxError("local repo path is outside the allowed root")
    return str(path)


async def clone_shallow(
    source: RepoSource,
    dest: Path,
    *,
    local_root: Path | None = None,
    timeout_s: float = CLONE_TIMEOUT_S,
    git_env: Mapping[str, str] | None = None,
    at: str | None = None,
) -> None:
    """Clone `source` into `dest` (which must not exist) with depth 1.

    With `at`, a commit id, the clone's branch is then moved to that commit (fetched at depth 1
    if the branch has moved on since): a run's later attempts work on the commit its first one
    cloned (12.2). Only the https and file transports are enabled, prompts are off, and the
    user's and system's git config are ignored. `git_env` (e.g. a GitHub token as an HTTP
    header, through `GIT_CONFIG_*`) is added to git's environment for an https source only; it
    never reaches the clone's own config. Raises `SandboxError` with a message free of host paths
    if the clone fails, or if `at` is not a commit id or is no longer in the repo.
    """
    if at is not None and not COMMIT_ID.match(at):
        raise SandboxError("not a commit id")
    url = _local_repo(source, local_root) if source.is_local else source.url
    transports = [
        "-c", "protocol.allow=never",
        "-c", "protocol.https.allow=always",
        "-c", "protocol.file.allow=always",
    ]  # fmt: skip
    argv = [
        "git", *transports,
        "clone", "--depth", "1", "--no-tags", "--single-branch", "--no-local",
        *(["--branch", source.ref] if source.ref else []),
        "--", url, str(dest),
    ]  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="agentic-git-") as config_dir:
        config = Path(config_dir) / "gitconfig"
        # A local repo is often owned by another user (e.g. mounted into the worker container).
        # It is confined to `local_root` and only read. git honours `safe.directory` only from
        # global or system config, so it goes in this clone's own global config.
        trusted = f"[safe]\n\tdirectory = {Path(url).as_posix()}\n" if source.is_local else ""
        await asyncio.to_thread(config.write_text, trusted, encoding="utf-8")
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(config),
            **({} if source.is_local else dict(git_env or {})),
        }
        await _git(argv, env, timeout_s, url, dest)
        if at is None or await _head(dest, env) == at:
            return
        git = ["git", "-C", str(dest), *transports]
        fetch = [*git, "fetch", "-q", "--depth", "1", "--no-tags", "origin", at]
        try:
            await _git(fetch, env, timeout_s, url, dest, doing="fetch the run's base commit")
            await _git(
                [*git, "reset", "-q", "--hard", at],
                env,
                timeout_s,
                url,
                dest,
                doing="check out the run's base commit",
            )
        except SandboxError as e:
            raise SandboxError(f"the commit the run started from ({at[:12]}) is gone: {e}") from e


COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")
"""A full commit id, as a run's base commit is recorded (12.2)."""


async def _head(dest: Path, env: dict[str, str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(dest), "rev-parse", "HEAD",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return out.decode().strip()


async def _git(
    argv: list[str],
    env: dict[str, str],
    timeout_s: float,
    url: str,
    dest: Path,
    *,
    doing: str = "clone the repo",
) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as e:
        raise SandboxError("git is not available on this worker") from e
    try:
        async with asyncio.timeout(timeout_s):
            _, stderr = await proc.communicate()
    except TimeoutError:
        raise SandboxError(f"git took longer than {timeout_s:g} s to {doing}") from None
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        raise SandboxError(f"could not {doing}: {_git_error(stderr, url, dest)}")


def _git_error(stderr: bytes, url: str, dest: Path) -> str:
    """git's last `fatal:` line, with host paths replaced."""
    lines = [ln.strip() for ln in stderr.decode("utf-8", errors="replace").splitlines()]
    fatal = [ln for ln in lines if ln.startswith("fatal:")]
    message = (fatal or [ln for ln in lines if ln] or ["git clone failed"])[-1]
    message = message.removeprefix("fatal:").strip()
    for path in {str(dest), dest.as_posix(), url, Path(url).as_posix()}:
        message = message.replace(path, "<repo>")
    return message
