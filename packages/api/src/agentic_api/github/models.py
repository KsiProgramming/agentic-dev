from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentic_engine.templates import Gitignore, License
from agentic_github import RepoInfo


class StartInstall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_to: Annotated[
        str | None,
        Field(
            max_length=500,
            # A path of the web app only, never another origin (`//host`, `/\host`).
            pattern=r"^/([^/\\\s]\S*)?$",
            description="Where the web app lands after the install, e.g. "
            "`/templates?template=generate-docs`. Defaults to the settings page.",
        ),
    ] = None


class InstallUrlOut(BaseModel):
    """Where to send the browser to install the GitHub App. The URL is valid for 10 minutes."""

    install_url: str


class RepoOut(BaseModel):
    """A repo the workspace's GitHub App installation can reach."""

    id: int
    full_name: str
    name: str
    owner: str
    private: bool
    default_branch: str
    html_url: str

    @classmethod
    def of(cls, info: RepoInfo) -> "RepoOut":
        return cls(
            id=info.id,
            full_name=info.full_name,
            name=info.name,
            owner=info.owner,
            private=info.private,
            default_branch=info.default_branch,
            html_url=info.html_url,
        )


class GithubErrorDetail(BaseModel):
    """The `detail` of a 409 from a GitHub endpoint, or from a run on a new repo: `code` says
    what the user should do (`no_connection`, `installation_gone`, `personal_account`,
    `repo_exists`)."""

    code: str
    message: str


type NewRepoReason = Literal["no_connection", "installation_gone", "personal_account"]


class NewRepoOptions(BaseModel):
    """Whether the workspace can start a run on a new repo (`new_repo` on `POST /runs`), where
    the repo would be, and what its first commit may hold."""

    owner: str | None = Field(description="The organisation the repo is created in.")
    can_create: bool
    reason: NewRepoReason | None = Field(
        default=None, description="Why not: the code of the 409 a run on a new repo would get."
    )
    message: str | None = Field(default=None, description="Why not, for people.")
    gitignore_templates: list[Gitignore]
    licenses: list[License]
