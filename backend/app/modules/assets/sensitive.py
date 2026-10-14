# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Encrypted custom fields (master M2.1-T2, §B8.1 Custom fields, §B11.4, §C5.2 Sensitive class).

Encryption happens before the write transaction opens: `encrypt_custom_fields` collects every
encrypted value of one write and sends them to the secrets provider in a single `encrypt_many`
call. If that call fails, the caller raises `SecretsUnavailableError` (503
`platform.secrets_unavailable`) *before* starting the transaction, so nothing is written.

Each value is bound to its own context (`asset:<organization_id>:<field_key>`), so a ciphertext
from one field or one organization can never be replayed into another (§B8.1). Decryption is only
for a detail read by a member holding `asset.read_sensitive`; a list, export or public scan never
calls it (§C5.2).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping

from app.modules.assets.custom_fields import JsonValue
from app.providers.secrets.base import SecretsProvider

__all__ = [
    "decrypt_custom_fields",
    "encrypt_custom_fields",
    "encrypted_field_presence",
    "sensitive_field_context",
]


def sensitive_field_context(organization_id: str, field_key: str) -> str:
    """Context string binding a ciphertext to one organization and one field key (§B8.1)."""
    return f"asset:{organization_id}:{field_key}"


async def encrypt_custom_fields(
    provider: SecretsProvider,
    *,
    organization_id: str,
    plaintexts: Mapping[str, str],
) -> dict[str, str]:
    """Encrypt every `{field_key: plaintext}` pair of one write in a single `encrypt_many` call.

    Returns `{field_key: ciphertext}` for `assets.encrypted_fields`. Raises
    `SecretsUnavailableError` (from the provider) and writes nothing if any item fails: this must
    run, and complete, before the caller opens its write transaction.
    """
    if not plaintexts:
        return {}
    keys = list(plaintexts.keys())
    items = [(sensitive_field_context(organization_id, key), plaintexts[key]) for key in keys]
    ciphertexts = await provider.encrypt_many(items)
    return dict(zip(keys, ciphertexts, strict=True))


async def decrypt_custom_fields(
    provider: SecretsProvider,
    *,
    organization_id: str,
    ciphertexts: Mapping[str, str],
) -> dict[str, JsonValue]:
    """Decrypt every `{field_key: ciphertext}` pair; detail reads only, gated by `asset.read_sensitive`.

    Each plaintext was JSON-encoded by `custom_fields._store` before encryption (so any field type,
    not only text, round-trips exactly); this reverses that encoding back to the typed value.
    """
    out: dict[str, JsonValue] = {}
    for key, ciphertext in ciphertexts.items():
        plaintext = await provider.decrypt(sensitive_field_context(organization_id, key), ciphertext)
        out[key] = json.loads(plaintext)
    return out


def encrypted_field_presence(
    encrypted_field_keys: Collection[str], stored: Mapping[str, str]
) -> dict[str, dict[str, bool]]:
    """Without `asset.read_sensitive`: every encrypted field as `{"is_set": true|false}` only (§B8.1).

    `encrypted_field_keys` is every encrypted field the category defines; `stored` is
    `assets.encrypted_fields` (key -> ciphertext). Never includes a plaintext or ciphertext value.
    """
    return {key: {"is_set": key in stored} for key in encrypted_field_keys}
