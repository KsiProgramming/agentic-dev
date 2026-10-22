from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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
    """The `detail` of a 409 from the repos endpoint: `code` says what the user should do."""

    code: str
    message: str
