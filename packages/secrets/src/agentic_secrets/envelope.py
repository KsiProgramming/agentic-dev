"""Secrets encrypted with AES-256-GCM under a workspace's data key (DEK).

The associated data names the row a ciphertext belongs to, so a ciphertext copied to another row
or workspace fails to decrypt instead of being used there."""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from agentic_secrets.errors import SecretDecryptError
from agentic_secrets.keys import KEY_BYTES, NONCE_BYTES


def new_dek() -> bytes:
    return AESGCM.generate_key(bit_length=KEY_BYTES * 8)


def encrypt(dek: bytes, secret: SecretStr, aad: bytes) -> tuple[bytes, bytes]:
    """Returns `(nonce, ciphertext)`."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(dek).encrypt(nonce, secret.get_secret_value().encode(), aad)


def decrypt(dek: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> SecretStr:
    try:
        plaintext = AESGCM(dek).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise SecretDecryptError("the secret could not be decrypted") from None
    return SecretStr(plaintext.decode())


def hint(secret: SecretStr) -> str:
    """The last 4 characters, shown so a user can tell which key is stored."""
    return secret.get_secret_value()[-4:]
