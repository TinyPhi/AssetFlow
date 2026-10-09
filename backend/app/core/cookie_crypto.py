# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AES-GCM cookie encryption and decryption for BFF session management (§B11.2, §B7.2)."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.problems import UnauthorizedError

_NONCE_LEN: Final = 12


def derive_key(raw_key: str | bytes) -> bytes:
    """Derive a 32-byte (256-bit) AES-GCM key from any string or byte input using SHA-256."""
    if isinstance(raw_key, str):
        raw_key = raw_key.encode("utf-8")
    return hashlib.sha256(raw_key).digest()


def encrypt_cookie(plaintext: str, key: bytes) -> str:
    """Encrypt plaintext string using AES-GCM and return URL-safe base64 encoded token."""
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_cookie(ciphertext_b64: str, key: bytes) -> str:
    """Decrypt URL-safe base64 encoded AES-GCM token; raise UnauthorizedError on failure."""
    if not ciphertext_b64:
        raise UnauthorizedError("Session cookie is missing or invalid.")
    try:
        payload = base64.urlsafe_b64decode(ciphertext_b64.encode("ascii"))
        if len(payload) < _NONCE_LEN + 16:
            raise UnauthorizedError("Session cookie is invalid.")
        nonce = payload[:_NONCE_LEN]
        ciphertext = payload[_NONCE_LEN:]
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise UnauthorizedError("Session cookie is invalid or expired.") from exc
