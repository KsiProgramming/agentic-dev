import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from agentic_secrets import (
    KEY_BYTES,
    LocalKeyProvider,
    SecretDecryptError,
    SecretsConfigError,
    WrappedKey,
    decrypt,
    encrypt,
    generate_key_file,
    hint,
    new_dek,
)
from agentic_secrets.__main__ import main

SECRET = SecretStr("sk-ant-test-0123456789abcd")
AAD = b"workspace:1/connection:2"


def test_round_trip() -> None:
    dek = new_dek()
    nonce, ciphertext = encrypt(dek, SECRET, AAD)

    assert SECRET.get_secret_value().encode() not in ciphertext
    assert decrypt(dek, nonce, ciphertext, AAD) == SECRET


def test_tampered_ciphertext_fails() -> None:
    dek = new_dek()
    nonce, ciphertext = encrypt(dek, SECRET, AAD)
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]

    with pytest.raises(SecretDecryptError) as caught:
        decrypt(dek, nonce, tampered, AAD)
    assert SECRET.get_secret_value() not in str(caught.value)


def test_wrong_aad_fails() -> None:
    dek = new_dek()
    nonce, ciphertext = encrypt(dek, SECRET, AAD)

    with pytest.raises(SecretDecryptError):
        decrypt(dek, nonce, ciphertext, b"workspace:other/connection:2")


def test_wrong_data_key_fails() -> None:
    nonce, ciphertext = encrypt(new_dek(), SECRET, AAD)

    with pytest.raises(SecretDecryptError):
        decrypt(new_dek(), nonce, ciphertext, AAD)


def test_a_data_key_round_trips_through_the_master_key() -> None:
    keys = LocalKeyProvider(os.urandom(KEY_BYTES))
    dek = new_dek()

    wrapped = keys.wrap(dek, b"workspace:1")

    assert dek not in wrapped.blob
    assert wrapped.key_id == keys.key_id
    assert keys.unwrap(wrapped, b"workspace:1") == dek


def test_wrong_master_key_fails() -> None:
    wrapped = LocalKeyProvider(os.urandom(KEY_BYTES)).wrap(new_dek(), b"workspace:1")
    other = LocalKeyProvider(os.urandom(KEY_BYTES))

    with pytest.raises(SecretDecryptError, match="wrapped by master key"):
        other.unwrap(wrapped, b"workspace:1")
    # Same id but different bytes (a forged or corrupted key id) still fails on the tag.
    with pytest.raises(SecretDecryptError):
        other.unwrap(WrappedKey(other.key_id, wrapped.blob), b"workspace:1")


def test_a_data_key_is_bound_to_its_context() -> None:
    keys = LocalKeyProvider(os.urandom(KEY_BYTES))
    wrapped = keys.wrap(new_dek(), b"workspace:1")

    with pytest.raises(SecretDecryptError):
        keys.unwrap(wrapped, b"workspace:2")


def test_key_file_checks(tmp_path: Path) -> None:
    with pytest.raises(SecretsConfigError, match="no master key file"):
        LocalKeyProvider.from_file(tmp_path / "missing.key")

    short = tmp_path / "short.key"
    short.write_bytes(b"too short")
    with pytest.raises(SecretsConfigError, match="must hold 32 bytes"):
        LocalKeyProvider.from_file(short)


def test_generated_key_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "master.key"
    generate_key_file(path)

    assert len(path.read_bytes()) == KEY_BYTES
    assert LocalKeyProvider.from_file(path).key_id.startswith("local:")


def test_generate_key_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    assert main(["generate-key", str(path)]) == 0
    original = path.read_bytes()

    assert main(["generate-key", str(path)]) == 1
    assert main(["generate-key", str(path), "--if-missing"]) == 0
    assert path.read_bytes() == original


def test_hint_is_the_last_four_characters() -> None:
    assert hint(SECRET) == "abcd"
