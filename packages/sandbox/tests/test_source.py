from pathlib import Path

import pytest
from pydantic import ValidationError

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
