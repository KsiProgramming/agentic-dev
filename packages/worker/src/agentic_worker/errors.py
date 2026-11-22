class RunSetupError(RuntimeError):
    """A run cannot start on this worker, e.g. its workspace has no key for its provider. The
    run fails with this message, which is safe to show (it never holds a secret)."""
