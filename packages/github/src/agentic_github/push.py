"""Pushing a writer's branch to GitHub from a git bundle, on the worker host.

A run's sandbox has no network, so its commits leave it as a bundle (`<base>..<branch>`). The
push happens in a throwaway repo on the worker: a depth-1 fetch of the base commit (the bundle's
prerequisite), a fetch of the bundle, a check that the branch grows from the base, then a push
that may only create the branch, or find it already at the same commit (a retried node).

A follow-up of a pull request review (7.6) pushes onto the pull request's branch instead
(`onto`): only as a fast-forward from the commit the run expects there, which a lease makes
atomic. If anyone else pushed to it, nothing is pushed (`PR_HEAD_MOVED`).

The installation token reaches git through the environment (`GIT_CONFIG_*`, as an HTTP header),
never through argv, a remote URL or a config file. git reads no system or user config, runs no
hooks and never prompts. Error messages carry git's reason, never the token.
"""

import asyncio
import base64
import contextlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from agentic_github.errors import PushError

PUSH_TIMEOUT_S = 120.0
GITHUB_WEB = "https://github.com"

_GITHUB_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<name>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)
_PR_URL = re.compile(
    r"^https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}/pull/"
    r"(?P<number>[1-9][0-9]{0,9})$"
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
PR_HEAD_MOVED = "pr_head_moved"
"""The code of a push onto a pull request's branch that someone else moved (7.6)."""
# A branch git accepts and we can pass as an argument: no leading `-`, no `..`, no spaces.
_BRANCH = re.compile(r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$")


def repo_full_name(url: str) -> str | None:
    """`owner/name` for a GitHub repo URL (`https://github.com/<owner>/<name>(.git)`), else
    `None`."""
    match = _GITHUB_URL.match(url)
    if match is None or match["name"] in {".", ".."}:
        return None
    return f"{match['owner']}/{match['name']}"


def pr_number(url: str) -> int | None:
    """The number of a pull request URL on github.com, else `None`."""
    match = _PR_URL.match(url)
    return int(match["number"]) if match else None


@dataclass(frozen=True)
class PushOnto:
    """Push onto an existing branch (a pull request's head, 7.6) as a fast-forward from
    `expected`, the commit the run last pushed there."""

    branch: str
    expected: str


def github_remote(full_name: str) -> str:
    return f"{GITHUB_WEB}/{full_name}.git"


def auth_env(token: SecretStr) -> dict[str, str]:
    """Environment that makes git send `token` (an installation token) to GitHub over https."""
    basic = base64.b64encode(f"x-access-token:{token.get_secret_value()}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


async def push_bundle(
    bundle: bytes,
    *,
    remote_url: str,
    base_sha: str,
    branch: str,
    token: SecretStr | None,
    timeout_s: float = PUSH_TIMEOUT_S,
    onto: PushOnto | None = None,
) -> str:
    """Push `branch` from `bundle` to `remote_url` and return the commit it points at.

    The branch must not exist on the remote yet, or already point at that commit. With `onto`,
    it is pushed as `onto.branch` instead, which must be at `onto.expected` (or already at the
    commit), and the commit must grow from it: else `PushError` starting `pr_head_moved:`. Only
    https remotes are allowed, and `file://` ones for tests. Raises `PushError`."""
    if not _SHA.match(base_sha):
        raise PushError("the base commit is not a full commit id")
    if not _BRANCH.match(branch) or ".." in branch:
        raise PushError("not a branch name we push")
    if onto is not None and (
        not _BRANCH.match(onto.branch) or ".." in onto.branch or not _SHA.match(onto.expected)
    ):
        raise PushError("not a pull request branch we push onto")
    if not (remote_url.startswith("https://") or remote_url.startswith("file://")):
        raise PushError("only https remotes are supported")
    ref = f"refs/heads/{branch}"
    work = Path(tempfile.mkdtemp(prefix="agentic-push-"))
    git = _Git(work / "repo", remote_url, token, timeout_s)
    try:
        await asyncio.to_thread((work / "branch.bundle").write_bytes, bundle)
        await git.run("init", "-q", str(work / "repo"), cwd=work)
        await git.run("fetch", "-q", "--no-tags", "--depth", "1", remote_url, base_sha)
        await git.run("bundle", "verify", "-q", str(work / "branch.bundle"))
        await git.fetch_bundle(work / "branch.bundle", ref)
        head = (await git.run("rev-parse", "--verify", f"{ref}^{{commit}}")).strip()
        try:
            await git.run("merge-base", "--is-ancestor", base_sha, ref)
        except PushError:
            raise PushError("the branch does not grow from the run's base commit") from None
        if onto is not None:
            return await _push_onto(git, remote_url, ref, head, onto)
        # An empty lease: the push may only create the ref (or find it at `head` already).
        await git.run(
            "push", "--porcelain", f"--force-with-lease={ref}:", remote_url, f"{ref}:{ref}"
        )
        return head
    finally:
        await asyncio.to_thread(shutil.rmtree, work, ignore_errors=True)


async def _push_onto(git: "_Git", remote_url: str, ref: str, head: str, onto: PushOnto) -> str:
    target = f"refs/heads/{onto.branch}"
    listed = (await git.run("ls-remote", remote_url, target)).split()
    current = listed[0] if listed else None
    if current == head:
        return head  # a retried node pushed it already
    if current != onto.expected:
        raise PushError(
            f"{PR_HEAD_MOVED}: the pull request's branch {onto.branch} is no longer at the commit "
            "this run started from; someone else pushed to it"
        )
    try:
        await git.run("merge-base", "--is-ancestor", onto.expected, ref)
    except PushError:
        raise PushError(
            f"{PR_HEAD_MOVED}: the run's branch does not grow from the pull request's head"
        ) from None
    try:
        await git.run(
            "push", "--porcelain", f"--force-with-lease={target}:{onto.expected}", remote_url,
            f"{ref}:{target}",
        )  # fmt: skip
    except PushError:
        raise PushError(
            f"{PR_HEAD_MOVED}: the pull request's branch {onto.branch} moved while pushing"
        ) from None
    return head


class _Git:
    def __init__(
        self, repo: Path, remote_url: str, token: SecretStr | None, timeout_s: float
    ) -> None:
        self._repo = repo
        self._remote = remote_url
        self._token = token
        self._timeout_s = timeout_s
        protocols = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
        if remote_url.startswith("file://"):
            protocols += ["-c", "protocol.file.allow=always"]
        self._options = [
            *protocols,
            "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.fsmonitor=false",
            "-c", "credential.helper=",
        ]  # fmt: skip
        self._env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            **(auth_env(token) if token is not None else {}),
        }

    async def fetch_bundle(self, bundle: Path, ref: str) -> None:
        """Fetch `ref` from the local `bundle`. git checks the file transport for a bundle
        path, so it is allowed for this command only; the remote stays https."""
        await self.run(
            "fetch", "-q", "--no-tags", str(bundle), f"{ref}:{ref}",
            allow=("-c", "protocol.file.allow=always"),
        )  # fmt: skip

    async def run(self, *args: str, cwd: Path | None = None, allow: tuple[str, ...] = ()) -> str:
        argv = ["git", *self._options, *allow, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd or self._repo,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError:
            raise PushError("git is not available on this worker") from None
        try:
            async with asyncio.timeout(self._timeout_s):
                out, err = await proc.communicate()
        except TimeoutError:
            raise PushError(f"git {args[0]} took longer than {self._timeout_s:g} s") from None
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        stdout = out.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise PushError(self._reason(args[0], stdout, err.decode("utf-8", errors="replace")))
        return stdout

    def _reason(self, command: str, stdout: str, stderr: str) -> str:
        """Why `git <command>` failed, in git's words, without the token or host paths."""
        if command == "push" and ("stale info" in stdout or "[rejected]" in stdout):
            return "the branch already exists on GitHub with other commits"
        lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
        fatal = [ln for ln in lines if ln.startswith(("fatal:", "error:"))]
        message = (fatal or lines or [f"git {command} failed"])[-1]
        message = message.removeprefix("fatal:").removeprefix("error:").strip()
        if self._token is not None:
            message = message.replace(self._token.get_secret_value(), "[REDACTED]")
        for path in {str(self._repo.parent), self._repo.parent.as_posix()}:
            message = message.replace(path, "<tmp>")
        return f"git {command} failed: {message}"
