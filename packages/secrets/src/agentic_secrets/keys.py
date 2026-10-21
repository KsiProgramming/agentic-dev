"""Master keys that wrap the per-workspace data keys.

A `KeyProvider` is the KMS: it never hands out its key, it only wraps and unwraps data keys. The
local provider reads a key file (dev); a cloud KMS provider replaces it behind the same protocol.
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agentic_secrets.errors import SecretDecryptError, SecretsConfigError

KEY_BYTES = 32
NONCE_BYTES = 12


@dataclass(frozen=True)
class WrappedKey:
    """A data key encrypted by a master key. `blob` is opaque to everyone but its provider."""

    key_id: str
    blob: bytes


class KeyProvider(Protocol):
    """Wraps data keys. `context` is bound to the wrapped key: unwrapping needs the same one."""

    @property
    def key_id(self) -> str: ...

    def wrap(self, dek: bytes, context: bytes) -> WrappedKey: ...

    def unwrap(self, wrapped: WrappedKey, context: bytes) -> bytes: ...


class LocalKeyProvider:
    """A 32-byte master key from a local file; it wraps data keys with AES-256-GCM.

    `key_id` is derived from the key, so a data key wrapped under another master key is told
    apart before decrypting."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != KEY_BYTES:
            raise SecretsConfigError(f"the master key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(master_key)
        digest = hashlib.sha256(b"agentic-key-id:" + master_key).hexdigest()
        self._key_id = f"local:{digest[:16]}"

    @classmethod
    def from_file(cls, path: Path) -> "LocalKeyProvider":
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise SecretsConfigError(f"no master key file at {path}") from None
        except OSError as e:
            raise SecretsConfigError(f"cannot read the master key file at {path}: {e}") from None
        if len(data) != KEY_BYTES:
            raise SecretsConfigError(f"the master key file at {path} must hold {KEY_BYTES} bytes")
        return cls(data)

    @property
    def key_id(self) -> str:
        return self._key_id

    def wrap(self, dek: bytes, context: bytes) -> WrappedKey:
        nonce = os.urandom(NONCE_BYTES)
        return WrappedKey(self._key_id, nonce + self._aead.encrypt(nonce, dek, context))

    def unwrap(self, wrapped: WrappedKey, context: bytes) -> bytes:
        if wrapped.key_id != self._key_id:
            raise SecretDecryptError(
                f"the data key was wrapped by master key {wrapped.key_id}, not {self._key_id}"
            )
        nonce, ciphertext = wrapped.blob[:NONCE_BYTES], wrapped.blob[NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, ciphertext, context)
        except InvalidTag:
            raise SecretDecryptError("the data key could not be unwrapped") from None


def generate_key_file(path: Path) -> None:
    """Writes a new random master key to `path` (mode 0600). Never overwrites an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(AESGCM.generate_key(bit_length=KEY_BYTES * 8))
