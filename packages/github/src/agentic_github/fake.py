"""A stand-in for the platform's GitHub App, for local dev and end-to-end tests
(`AGENTIC_GITHUB=fake`). It never calls GitHub.

It has one installation, on the `e2e-org` organisation, which reaches the repos in
`FAKE_REPOS`. Installing it sends the browser straight back to the API's setup URL. Their
clones and pushes go to bare repos under a local fixtures directory (`fixture_path`), and pull
requests are numbered in memory.

Given that directory (`fixtures_root`), it also creates repos: each is a bare repo there with one
scaffold commit, and its settings are kept in the bare repo's git config, so the API and the
worker (two processes) see the same repos."""

import asyncio
import itertools
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from pydantic import SecretStr

from agentic_github.errors import InstallationNotFoundError, RepoExistsError
from agentic_github.models import InstallationInfo, PullRequestInfo, RepoInfo

FAKE_INSTALLATION_ID = 1
FAKE_ACCOUNT = "e2e-org"
FAKE_REPOS = (
    RepoInfo(
        id=1001,
        full_name=f"{FAKE_ACCOUNT}/docs-demo",
        name="docs-demo",
        owner=FAKE_ACCOUNT,
        private=False,
        default_branch="main",
        html_url=f"https://github.com/{FAKE_ACCOUNT}/docs-demo",
    ),
    RepoInfo(
        id=1002,
        full_name=f"{FAKE_ACCOUNT}/private-lib",
        name="private-lib",
        owner=FAKE_ACCOUNT,
        private=True,
        default_branch="main",
        html_url=f"https://github.com/{FAKE_ACCOUNT}/private-lib",
    ),
)

# Git config keys marking a bare repo the fake created, with its settings.
_CREATED_AT = "agentic.createdAt"
_PRIVATE = "agentic.private"
_ID = "agentic.id"


def fixture_path(fixtures_root: Path, full_name: str) -> Path:
    """The bare repo standing in for `full_name` (`<root>/<owner>/<name>.git`)."""
    return fixtures_root / f"{full_name}.git"


class FakeGithubApp:
    """Has `GithubApp`'s interface. `api_base_url` is where the browser reaches the API, which
    the fake install flow sends it back to; `fixtures_root` is where its bare repos are (without
    it, it cannot create repos)."""

    def __init__(self, api_base_url: str, fixtures_root: Path | None = None) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._fixtures_root = fixtures_root
        self._numbers = itertools.count(1)

    def install_url(self, state: str) -> str:
        query = urlencode(
            {"installation_id": FAKE_INSTALLATION_ID, "setup_action": "install", "state": state}
        )
        return f"{self._api_base_url}/github/setup?{query}"

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        self._check(installation_id)
        return InstallationInfo(
            id=installation_id, account_login=FAKE_ACCOUNT, account_type="Organization"
        )

    async def list_repos(self, installation_id: int) -> list[RepoInfo]:
        self._check(installation_id)
        return [*FAKE_REPOS, *await asyncio.to_thread(self._created_repos)]

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None:
        self._check(installation_id)
        fixed = next((r for r in FAKE_REPOS if r.full_name == full_name), None)
        return fixed or await asyncio.to_thread(self._created_repo, full_name)

    async def create_org_repo(
        self,
        installation_id: int,
        org: str,
        name: str,
        *,
        private: bool,
        description: str | None = None,
        gitignore_template: str | None = None,
        license_template: str | None = None,
    ) -> RepoInfo:
        self._check(installation_id)
        if org != FAKE_ACCOUNT:
            raise InstallationNotFoundError(installation_id)
        if self._fixtures_root is None:
            raise RuntimeError("the fake GitHub App creates repos only with a fixtures root")
        full_name = f"{org}/{name}"
        if await self.get_repo(installation_id, full_name) is not None:
            raise RepoExistsError(f"repo {full_name} already exists")
        files = _scaffold(name, description, gitignore_template, license_template)
        bare = fixture_path(self._fixtures_root, full_name)
        await asyncio.to_thread(_create_bare_repo, bare, files, private=private)
        created = await asyncio.to_thread(self._created_repo, full_name)
        assert created is not None
        return created

    async def installation_token(self, installation_id: int) -> SecretStr:
        self._check(installation_id)
        return SecretStr("fake-installation-token")

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo:
        self._check(installation_id)
        number = next(self._numbers)
        return PullRequestInfo(
            number=number, url=f"https://github.com/{full_name}/pull/{number}", head=head, base=base
        )

    def close(self) -> None:
        pass

    def _created_repos(self) -> list[RepoInfo]:
        if self._fixtures_root is None:
            return []
        names = sorted(p.name.removesuffix(".git") for p in self._owner_dir().glob("*.git"))
        repos = (self._created_repo(f"{FAKE_ACCOUNT}/{name}") for name in names)
        return [r for r in repos if r is not None]

    def _created_repo(self, full_name: str) -> RepoInfo | None:
        """A repo the fake created (its bare repo has our marks), or `None`."""
        if self._fixtures_root is None:
            return None
        bare = fixture_path(self._fixtures_root, full_name)
        created_at = _config(bare, _CREATED_AT)
        if created_at is None:
            return None
        owner, name = full_name.split("/", 1)
        return RepoInfo(
            id=int(_config(bare, _ID) or 0),
            full_name=full_name,
            name=name,
            owner=owner,
            private=_config(bare, _PRIVATE) == "true",
            default_branch="main",
            html_url=f"https://github.com/{full_name}",
            created_at=datetime.fromisoformat(created_at),
        )

    def _owner_dir(self) -> Path:
        assert self._fixtures_root is not None
        return self._fixtures_root / FAKE_ACCOUNT

    @staticmethod
    def _check(installation_id: int) -> None:
        if installation_id != FAKE_INSTALLATION_ID:
            raise InstallationNotFoundError(installation_id)


def _scaffold(
    name: str, description: str | None, gitignore: str | None, license_: str | None
) -> dict[str, str]:
    """What GitHub's `auto_init` commits, roughly: a README, and the templates asked for."""
    files = {"README.md": f"# {name}\n" + (f"\n{description}\n" if description else "")}
    if gitignore:
        files[".gitignore"] = f"# {gitignore} .gitignore (fake template)\n.env\n"
    if license_:
        files["LICENSE"] = f"{license_} License (fake template)\n"
    return files


def _create_bare_repo(bare: Path, files: dict[str, str], *, private: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for path, text in files.items():
            (work / path).write_text(text, encoding="utf-8")
        _git(work, "init", "-q", "-b", "main")
        _git(work, "add", "-A")
        _git(
            work,
            "-c",
            "user.name=GitHub",
            "-c",
            "user.email=noreply@github.com",
            "commit",
            "-q",
            "-m",
            "Initial commit",
        )
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git(work, "clone", "-q", "--bare", str(work), str(bare))
    _git(bare, "config", _PRIVATE, "true" if private else "false")
    _git(bare, "config", _ID, str(2000 + sum(1 for _ in bare.parent.glob("*.git"))))
    # Last: a bare repo with this mark is a complete one.
    _git(bare, "config", _CREATED_AT, datetime.now(UTC).isoformat())


def _config(bare: Path, key: str) -> str | None:
    if not bare.is_dir():
        return None
    result = subprocess.run(
        ["git", "config", "--file", str(bare / "config"), "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
