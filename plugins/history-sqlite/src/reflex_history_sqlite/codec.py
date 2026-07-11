"""Authenticated encryption for history input and output fields."""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA_VERSION = 1
NONCE_SIZE = 12
METADATA_FIELDS = (
    "id",
    "created_at",
    "mode",
    "style",
    "scene",
    "provider",
    "model",
    "elapsed_ms",
    "status",
)
FIELD_ROLES = frozenset({"input", "output"})


def _invalid() -> ValueError:
    return ValueError("history_data_invalid")


def _frame(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _encode_value(value: str | int | None) -> bytes:
    if value is None:
        return b"\x00"
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return b"\x01" + _frame(encoded)
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return b"\x02" + value.to_bytes(8, "big", signed=True)
        except OverflowError as error:
            raise _invalid() from error
    raise _invalid()


@dataclass(frozen=True)
class HistoryMetadata:
    id: str
    created_at: str
    mode: str
    style: str
    scene: str | None
    provider: str
    model: str | None
    elapsed_ms: int | None
    status: str

    def __post_init__(self) -> None:
        required = (
            self.id,
            self.created_at,
            self.mode,
            self.style,
            self.provider,
            self.status,
        )
        if any(not isinstance(item, str) or not item for item in required):
            raise _invalid()
        if self.scene is not None and not isinstance(self.scene, str):
            raise _invalid()
        if self.model is not None and not isinstance(self.model, str):
            raise _invalid()
        if self.elapsed_ms is not None and (
            not isinstance(self.elapsed_ms, int)
            or isinstance(self.elapsed_ms, bool)
            or self.elapsed_ms < 0
        ):
            raise _invalid()


@dataclass(frozen=True)
class EncryptedField:
    nonce: bytes
    ciphertext: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.nonce, bytes) or not isinstance(self.ciphertext, bytes):
            raise _invalid()


def encode_metadata(metadata: HistoryMetadata) -> bytes:
    if not isinstance(metadata, HistoryMetadata):
        raise _invalid()
    return b"".join(
        _frame(field.encode("ascii")) + _encode_value(getattr(metadata, field))
        for field in METADATA_FIELDS
    )


def metadata_hash(metadata: HistoryMetadata) -> bytes:
    return hashlib.sha256(encode_metadata(metadata)).digest()


def encode_aad(
    schema_version: int,
    key_version: int,
    field_role: str,
    digest: bytes,
) -> bytes:
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or not 1 <= schema_version <= 2**31 - 1
        or not isinstance(key_version, int)
        or isinstance(key_version, bool)
        or not 1 <= key_version <= 1_000_000
        or field_role not in FIELD_ROLES
        or not isinstance(digest, bytes)
        or len(digest) != 32
    ):
        raise _invalid()
    return b"".join(
        (
            _frame(b"reflex-history-field"),
            b"\x02" + schema_version.to_bytes(4, "big"),
            b"\x02" + key_version.to_bytes(4, "big"),
            b"\x01" + _frame(field_role.encode("ascii")),
            b"\x03" + _frame(digest),
        )
    )


class HistoryCodec:
    def __init__(
        self,
        keys: Mapping[int, bytes],
        *,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        if not isinstance(keys, Mapping) or not keys:
            raise ValueError("history_key_unavailable")
        normalized: dict[int, bytes] = {}
        for version, key in keys.items():
            if (
                not isinstance(version, int)
                or isinstance(version, bool)
                or not 1 <= version <= 1_000_000
                or not isinstance(key, bytes)
                or len(key) != 32
            ):
                raise ValueError("history_key_unavailable")
            normalized[version] = key
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or not 1 <= schema_version <= 2**31 - 1
        ):
            raise _invalid()
        self._keys = normalized
        self._schema_version = schema_version

    def encrypt(
        self,
        plaintext: str,
        metadata: HistoryMetadata,
        key_version: int,
        field_role: str,
    ) -> EncryptedField:
        if not isinstance(plaintext, str):
            raise _invalid()
        key = self._key(key_version)
        nonce = os.urandom(NONCE_SIZE)
        aad = encode_aad(
            self._schema_version,
            key_version,
            field_role,
            metadata_hash(metadata),
        )
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return EncryptedField(nonce, ciphertext)

    def decrypt(
        self,
        encrypted: EncryptedField,
        metadata: HistoryMetadata,
        key_version: int,
        field_role: str,
    ) -> str:
        if not isinstance(encrypted, EncryptedField) or len(encrypted.nonce) != NONCE_SIZE:
            raise _invalid()
        key = self._key(key_version)
        aad = encode_aad(
            self._schema_version,
            key_version,
            field_role,
            metadata_hash(metadata),
        )
        plaintext = AESGCM(key).decrypt(encrypted.nonce, encrypted.ciphertext, aad)
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _invalid() from error

    def _key(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except (KeyError, TypeError) as error:
            raise ValueError("history_key_unavailable") from error
