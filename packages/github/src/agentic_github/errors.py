class GithubConfigError(RuntimeError):
    """The GitHub App settings are missing or malformed. The message never holds key material."""


class InstallationNotFoundError(LookupError):
    """GitHub does not know the installation, or our App can no longer reach it (uninstalled)."""


class GithubApiError(RuntimeError):
    """GitHub answered with an error, or could not be reached.

    The message carries only the status code or the error kind, never a token or a header."""


class PullRequestError(RuntimeError):
    """GitHub refused to open the pull request (e.g. no commits between the branches). The
    message is GitHub's reason, never a token."""


class PushError(RuntimeError):
    """A branch could not be pushed. The message is git's reason, never a token or host path."""
