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


class JiraNotFoundError(JiraApiError):
    """Jira answered `404`: the issue does not exist, or the account cannot see it."""


class JiraBadRequestError(JiraApiError):
    """Jira refused the request as malformed (`400`): an invalid JQL query, or a transition the
    issue does not offer."""


class JiraRateLimitedError(JiraApiError):
    """Jira answered `429` again after one wait, or asked for a wait longer than we take."""
