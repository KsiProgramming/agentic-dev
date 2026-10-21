class SecretsConfigError(RuntimeError):
    """The master key is missing or malformed. The message never holds key material."""


class SecretDecryptError(RuntimeError):
    """A secret or a data key could not be decrypted: wrong key, wrong context or tampered bytes.

    The message never holds key material or plaintext."""
