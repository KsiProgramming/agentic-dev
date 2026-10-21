"""Envelope encryption of workspace secrets (a master key wraps one data key per workspace) and
redaction of live secrets from logs and events."""

from agentic_secrets.envelope import decrypt, encrypt, hint, new_dek
from agentic_secrets.errors import SecretDecryptError, SecretsConfigError
from agentic_secrets.keys import (
    KEY_BYTES,
    KeyProvider,
    LocalKeyProvider,
    WrappedKey,
    generate_key_file,
)
from agentic_secrets.redact import (
    REDACTED,
    RedactingFilter,
    install_redaction,
    redact,
    redact_json,
    registered,
)

__all__ = [
    "KEY_BYTES",
    "REDACTED",
    "KeyProvider",
    "LocalKeyProvider",
    "RedactingFilter",
    "SecretDecryptError",
    "SecretsConfigError",
    "WrappedKey",
    "decrypt",
    "encrypt",
    "generate_key_file",
    "hint",
    "install_redaction",
    "new_dek",
    "redact",
    "redact_json",
    "registered",
]
