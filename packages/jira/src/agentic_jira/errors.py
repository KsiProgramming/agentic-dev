class JiraConfigError(RuntimeError):
    """The Atlassian OAuth app settings are missing or malformed. The message never holds the
    client secret."""


class JiraAuthError(RuntimeError):
    """Atlassian refused a grant. `reason` is fixed: `exchange` (the authorization code was not
    accepted) or `invalid_grant` (the refresh token is unknown, expired or revoked). The message
    never holds a code or a token."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Atlassian refused the grant: {reason}")
        self.reason = reason


class JiraUnauthorizedError(RuntimeError):
    """Atlassian did not accept the access token (expired, or the app's access was removed)."""


class JiraApiError(RuntimeError):
    """Atlassian answered with an error, or could not be reached.

    The message carries only the status code or the error kind, never a token or a body."""
