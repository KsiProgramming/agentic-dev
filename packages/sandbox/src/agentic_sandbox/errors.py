class SandboxError(RuntimeError):
    """A sandbox could not be created, filled or used.

    The message is safe to show in run events: it never holds host paths or credentials.
    """
