from pathlib import Path

import pytest
from pydantic import ValidationError

import agentic_sandbox.source
from agentic_sandbox import RepoSource, SandboxError, clone_shallow


@pytest.mark.parametrize(
    "url", ["https://github.com/octo/hello.git", "/samples/hello-repo", r"C:\repos\hello", "hello"]
)
def test_https_urls_and_local_paths_are_accepted(url: str) -> None:
    assert RepoSource(url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ssh://git@github.com/octo/hello.git",
        "git@github.com:octo/hello.git",
        "http://github.com/octo/hello.git",
        "file:///etc",
        "ext::sh -c touch% /tmp/pwned",
        "--upload-pack=touch /tmp/pwned",
        "https://user:token@github.com/octo/hello.git",
    ],
)
def test_other_sources_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        RepoSource(url=url)


@pytest.mark.parametrize("ref", ["-x", "a..b", "a b", ""])
def test_unsafe_refs_are_rejected(ref: str) -> None:
    with pytest.raises(ValidationError):
        RepoSource(url="https://github.com/octo/hello.git", ref=ref)


async def test_a_local_repo_is_cloned_at_depth_one(repos: Path, tmp_path: Path) -> None:
    dest = tmp_path / "clone"

    await clone_shallow(RepoSource(url=str(repos / "hello")), dest, local_root=repos)

    assert (dest / "src" / "pkg" / "deep" / "mod.py").read_text() == "X = 1\n"
    assert (dest / ".git" / "shallow").exists()


async def test_a_ref_is_checked_out(repos: Path, tmp_path: Path) -> None:
    await clone_shallow(
        RepoSource(url=str(repos / "hello"), ref="main"), tmp_path / "clone", local_root=repos
    )
    assert (tmp_path / "clone" / "README.md").exists()


async def test_local_paths_need_an_allowed_root(repos: Path, tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="not allowed"):
        await clone_shallow(RepoSource(url=str(repos / "hello")), tmp_path / "clone")


async def test_local_paths_outside_the_root_are_refused(repos: Path, tmp_path: Path) -> None:
    outside = RepoSource(url=str(repos / ".." / "elsewhere"))
    with pytest.raises(SandboxError, match="outside the allowed root"):
        await clone_shallow(outside, tmp_path / "clone", local_root=repos)


async def test_a_failed_clone_names_no_host_path(repos: Path, tmp_path: Path) -> None:
    missing = repos / "missing"
    with pytest.raises(SandboxError, match="could not clone the repo") as caught:
        await clone_shallow(RepoSource(url=str(missing)), tmp_path / "clone", local_root=repos)
    message = str(caught.value)
    assert str(tmp_path) not in message
    assert tmp_path.as_posix() not in message


async def test_an_unknown_ref_fails(repos: Path, tmp_path: Path) -> None:
    source = RepoSource(url=str(repos / "hello"), ref="no-such-branch")
    with pytest.raises(SandboxError, match="could not clone the repo"):
        await clone_shallow(source, tmp_path / "clone", local_root=repos)


HEADER = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "http.extraHeader",
    "GIT_CONFIG_VALUE_0": "x",
}


class _Captured:
    def __init__(self) -> None:
        self.argv: list[str] = []
        self.env: dict[str, str] = {}

    async def __call__(
        self, argv: list[str], env: dict[str, str], timeout_s: float, url: str, dest: Path
    ) -> None:
        self.argv, self.env = argv, env


async def test_git_env_reaches_an_https_clone_through_the_environment_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _Captured()
    monkeypatch.setattr(agentic_sandbox.source, "_git", captured)

    await clone_shallow(
        RepoSource(url="https://github.com/acme/private"), tmp_path / "clone", git_env=HEADER
    )

    assert {k: captured.env[k] for k in HEADER} == HEADER
    assert not any("extraHeader" in arg or arg == "x" for arg in captured.argv)


async def test_git_env_never_reaches_a_local_clone(
    repos: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _Captured()
    monkeypatch.setattr(agentic_sandbox.source, "_git", captured)

    await clone_shallow(
        RepoSource(url=str(repos / "hello")), tmp_path / "clone", local_root=repos, git_env=HEADER
    )

    assert captured.env.get("GIT_CONFIG_VALUE_0") != "x"


def _git(cwd: Path, *args: str) -> str:
    import os
    import subprocess

    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def test_a_clone_at_a_commit_stays_there_after_the_branch_moved_on(
    repos: Path, tmp_path: Path
) -> None:
    """12.2: a run's later attempts clone the commit its first one did, not the branch's tip."""
    origin = repos / "hello"
    base = _git(origin, "rev-parse", "HEAD")
    (origin / "LATER.md").write_text("later\n")
    _git(origin, "add", "LATER.md")
    _git(origin, "commit", "-q", "-m", "later")
    dest = tmp_path / "clone"

    await clone_shallow(RepoSource(url=str(origin)), dest, local_root=repos, at=base)

    assert _git(dest, "rev-parse", "HEAD") == base
    assert _git(dest, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"  # still on its branch
    assert not (dest / "LATER.md").exists()


async def test_a_clone_at_its_tip_needs_no_fetch(repos: Path, tmp_path: Path) -> None:
    base = _git(repos / "hello", "rev-parse", "HEAD")

    await clone_shallow(
        RepoSource(url=str(repos / "hello")), tmp_path / "c", local_root=repos, at=base
    )

    assert _git(tmp_path / "c", "rev-parse", "HEAD") == base


async def test_a_clone_at_a_commit_that_is_gone_fails_clearly(repos: Path, tmp_path: Path) -> None:
    with pytest.raises(
        SandboxError, match=r"the commit the run started from \(012345678901\) is gone"
    ):
        await clone_shallow(
            RepoSource(url=str(repos / "hello")),
            tmp_path / "c",
            local_root=repos,
            at="0123456789" * 4,
        )


async def test_only_a_full_commit_id_is_a_clone_s_base(repos: Path, tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="not a commit id"):
        await clone_shallow(
            RepoSource(url=str(repos / "hello")),
            tmp_path / "c",
            local_root=repos,
            at="--upload-pack=x",
        )
