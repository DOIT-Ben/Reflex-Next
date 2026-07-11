from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.exceptions import InvalidTag

from reflex_history_sqlite.codec import (
    EncryptedField,
    HistoryCodec,
    HistoryMetadata,
    encode_aad,
    encode_metadata,
)


KEY_V1 = bytes.fromhex("11" * 32)
KEY_V2 = bytes.fromhex("22" * 32)


@pytest.fixture
def metadata() -> HistoryMetadata:
    return HistoryMetadata(
        id="history-1",
        created_at="2026-07-11T10:00:00.000Z",
        mode="polish",
        style="concise",
        scene="coding",
        provider="minimax",
        model="MiniMax-M2.1",
        elapsed_ms=123,
        status="completed",
    )


def test_each_field_uses_a_fresh_96_bit_nonce(metadata):
    codec = HistoryCodec({1: KEY_V1})

    first = codec.encrypt("same text", metadata, 1, "input")
    second = codec.encrypt("same text", metadata, 1, "input")

    assert len(first.nonce) == 12
    assert len(second.nonce) == 12
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_decrypt_rejects_non_96_bit_nonce(metadata):
    codec = HistoryCodec({1: KEY_V1})

    with pytest.raises(ValueError, match="history_data_invalid"):
        codec.decrypt(EncryptedField(b"short", b"ciphertext"), metadata, 1, "input")


@pytest.mark.parametrize(
    ("changed_metadata", "key_version", "field_role"),
    [
        (lambda item: replace(item, provider="other"), 1, "input"),
        (lambda item: item, 2, "input"),
        (lambda item: item, 1, "output"),
        (lambda item: replace(item, scene=None), 1, "input"),
        (lambda item: replace(item, scene=""), 1, "input"),
    ],
)
def test_metadata_key_role_and_null_empty_substitution_are_authenticated(
    metadata, changed_metadata, key_version, field_role
):
    codec = HistoryCodec({1: KEY_V1, 2: KEY_V2})
    encrypted = codec.encrypt("private body", metadata, 1, "input")

    with pytest.raises(InvalidTag):
        codec.decrypt(
            encrypted,
            changed_metadata(metadata),
            key_version,
            field_role,
        )


def test_ciphertext_tampering_and_wrong_key_are_rejected(metadata):
    encrypted = HistoryCodec({1: KEY_V1}).encrypt(
        "private body", metadata, 1, "input"
    )
    tampered = EncryptedField(
        encrypted.nonce,
        encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1]),
    )

    with pytest.raises(InvalidTag):
        HistoryCodec({1: KEY_V1}).decrypt(tampered, metadata, 1, "input")
    with pytest.raises(InvalidTag):
        HistoryCodec({1: KEY_V2}).decrypt(encrypted, metadata, 1, "input")


def test_input_and_output_blobs_cannot_be_swapped(metadata):
    codec = HistoryCodec({1: KEY_V1})
    input_field = codec.encrypt("input body", metadata, 1, "input")
    output_field = codec.encrypt("output body", metadata, 1, "output")

    with pytest.raises(InvalidTag):
        codec.decrypt(output_field, metadata, 1, "input")
    with pytest.raises(InvalidTag):
        codec.decrypt(input_field, metadata, 1, "output")


def test_schema_version_is_authenticated(metadata):
    encrypted = HistoryCodec({1: KEY_V1}, schema_version=1).encrypt(
        "private body", metadata, 1, "input"
    )

    with pytest.raises(InvalidTag):
        HistoryCodec({1: KEY_V1}, schema_version=2).decrypt(
            encrypted, metadata, 1, "input"
        )


def test_metadata_and_aad_encodings_are_length_delimited_and_unambiguous(metadata):
    changed = replace(metadata, mode="pol", style="ishconcise")

    assert encode_metadata(metadata) != encode_metadata(changed)
    assert encode_aad(1, 23, "input", b"0" * 32) != encode_aad(
        12, 3, "input", b"0" * 32
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 1},
        {"created_at": None},
        {"elapsed_ms": "123"},
        {"status": ""},
    ],
)
def test_metadata_rejects_invalid_types_and_required_values(changes):
    values = dict(
        id="history-1",
        created_at="2026-07-11T10:00:00.000Z",
        mode="polish",
        style="concise",
        scene=None,
        provider="minimax",
        model=None,
        elapsed_ms=None,
        status="completed",
    )
    values.update(changes)

    with pytest.raises(ValueError, match="history_data_invalid"):
        HistoryMetadata(**values)
